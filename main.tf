provider "aws" {
    region = var.region
}

/*
    This second 'aws' provider is to allow cerificates to be provisioned in us-east-1
    This is needed because Cloudfront (which sits under edge optimised Custom Domains for API G/W) only supports
    certificates which are provisioned in ACM in us-east-1
*/
provider "aws" {
    alias = "useast"
    region = "us-east-1"
}

provider "archive" {}

data "aws_caller_identity" "current" {}

data "aws_route53_zone" "root_zone" {
    name         = "${var.root_domain}."
    private_zone = false
}

resource "null_resource" "lambda_packager" {
    triggers = {
        always_run = uuid()
    }
    provisioner "local-exec" {
        command = "mkdir -p ${path.root}/target_lambda"
    }
    provisioner "local-exec" {
        command = "pip3 install --upgrade --target=${path.root}/target_lambda -r requirements.txt"
    }
    provisioner "local-exec" {
        command = "cp -R ${path.root}/*.py ${path.root}/target_lambda/."
    }
}

data "archive_file" "zip" {
    type = "zip"
    source_dir = "target_lambda/"
    output_path = "function.zip"
    depends_on = [
        null_resource.lambda_packager
    ]
}

data "aws_iam_policy_document" "assume_policy" {
    statement {
        sid    = ""
        effect = "Allow"

        principals {
            identifiers = ["lambda.amazonaws.com"]
            type        = "Service"
        }

        actions = ["sts:AssumeRole"]
    }
}

data "aws_iam_policy_document" "lambda_permissions" {
    statement {
        sid         = ""
        effect      = "Allow"
        actions     = ["logs:CreateLogGroup"]
        resources   = [
            "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:*"
        ]
    }

    statement {
        sid         = ""
        effect      = "Allow"
        actions     = [
            "logs:CreateLogStream",
            "logs:PutLogEvents"
        ]
        resources   = [
            "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/UrlShortener-${var.env}:*"
        ]
    }

    statement {
        sid         = ""
        effect      = "Allow"
        actions     = [
            "dynamodb:PutItem",
            "dynamodb:GetItem",
            "dynamodb:UpdateItem",
            "dynamodb:Query"
        ]
        resources   = [
            "arn:aws:dynamodb:${var.region}:${data.aws_caller_identity.current.account_id}:table/UrlShortenerLinks_${var.env}",
            "arn:aws:dynamodb:${var.region}:${data.aws_caller_identity.current.account_id}:table/UrlShortenerLinks_${var.env}/index/*"
        ]
    }
}

resource "aws_iam_policy" "policy" {
    name        = "UrlShortener-${var.env}-policy"
    policy = data.aws_iam_policy_document.lambda_permissions.json
}

resource "aws_iam_role" "iam_for_lambda" {
    name               = "UrlShortener-${var.env}-role"
    assume_role_policy = data.aws_iam_policy_document.assume_policy.json
}

resource "aws_iam_role_policy_attachment" attach_policy_to_lambda_role {
  role       = aws_iam_role.iam_for_lambda.name
  policy_arn = aws_iam_policy.policy.arn
}

resource "aws_lambda_function" "lambda" {
    function_name       = "UrlShortener-${var.env}"

    filename            = data.archive_file.zip.output_path
    source_code_hash    = data.archive_file.zip.output_base64sha256

    role                = aws_iam_role.iam_for_lambda.arn
    handler             = "lambda_function.lambda_handler"
    runtime             = "python3.6"
    memory_size         = "256"
    timeout             = "10"

    environment {
        variables = {
            environment_name    = var.env
            cog_client_id       = aws_cognito_user_pool_client.app_client.id
            cog_client_secret   = aws_cognito_user_pool_client.app_client.client_secret
            cog_domain          = "${var.authdomain}-${var.env}"
            region              = var.region
        }
    }
}

resource "aws_api_gateway_rest_api" "apigw" {
    name        = "UrlShortener-${var.env}"
}

resource "aws_api_gateway_resource" "proxy" {
    rest_api_id = aws_api_gateway_rest_api.apigw.id
    parent_id   = aws_api_gateway_rest_api.apigw.root_resource_id
    path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "proxy" {
    rest_api_id   = aws_api_gateway_rest_api.apigw.id
    resource_id   = aws_api_gateway_resource.proxy.id
    http_method   = "GET"
    authorization = "NONE"
}

resource "aws_api_gateway_integration" "lambda" {
    rest_api_id = aws_api_gateway_rest_api.apigw.id
    resource_id = aws_api_gateway_method.proxy.resource_id
    http_method = aws_api_gateway_method.proxy.http_method

    integration_http_method = "POST"
    type                    = "AWS_PROXY"
    uri                     = aws_lambda_function.lambda.invoke_arn
}

/* 
    This second block of method and integration is because the above method/integration cannot match an empty resource path
*/
resource "aws_api_gateway_method" "proxy_root" {
    rest_api_id   = aws_api_gateway_rest_api.apigw.id
    resource_id   = aws_api_gateway_rest_api.apigw.root_resource_id
    http_method   = "POST"
    authorization = "COGNITO_USER_POOLS"
    authorizer_id = aws_api_gateway_authorizer.update_api_authoriser.id
}

resource "aws_api_gateway_integration" "lambda_root" {
    rest_api_id = aws_api_gateway_rest_api.apigw.id
    resource_id = aws_api_gateway_method.proxy_root.resource_id
    http_method = aws_api_gateway_method.proxy_root.http_method

    integration_http_method = "POST"
    type                    = "AWS_PROXY"
    uri                     = aws_lambda_function.lambda.invoke_arn
}

module "cors" {
  source = "github.com/squidfunk/terraform-aws-api-gateway-enable-cors"

  api_id          = aws_api_gateway_rest_api.apigw.id
  api_resource_id = aws_api_gateway_rest_api.apigw.root_resource_id
}

resource "aws_api_gateway_method" "proxy_root_get" {
    rest_api_id   = aws_api_gateway_rest_api.apigw.id
    resource_id   = aws_api_gateway_rest_api.apigw.root_resource_id
    http_method   = "GET"
    authorization = "NONE"
}

resource "aws_api_gateway_integration" "lambda_root_get" {
    rest_api_id = aws_api_gateway_rest_api.apigw.id
    resource_id = aws_api_gateway_method.proxy_root_get.resource_id
    http_method = aws_api_gateway_method.proxy_root_get.http_method

    integration_http_method = "POST"
    type                    = "AWS_PROXY"
    uri                     = aws_lambda_function.lambda.invoke_arn
}


resource "aws_lambda_permission" "lambda_permission" {
    action        = "lambda:InvokeFunction"
    function_name = aws_lambda_function.lambda.function_name
    principal     = "apigateway.amazonaws.com"
    source_arn = "${aws_api_gateway_rest_api.apigw.execution_arn}/*/*/*"
}

resource "aws_api_gateway_deployment" "apigwdeploy" {
    depends_on = [
        aws_api_gateway_integration.lambda,
        aws_api_gateway_integration.lambda_root,
    ]

    rest_api_id = aws_api_gateway_rest_api.apigw.id
    stage_name  = "api"
    variables = {
        env = var.env
    }
}

resource "aws_acm_certificate" "endpoint_cert" {
    provider          = aws.useast
    domain_name       = var.endpoint
    validation_method = "DNS"
}

resource "aws_route53_record" "endpoint_cert_validation" {
    name    = aws_acm_certificate.endpoint_cert.domain_validation_options.0.resource_record_name
    type    = aws_acm_certificate.endpoint_cert.domain_validation_options.0.resource_record_type
    zone_id = data.aws_route53_zone.root_zone.id
    records = [aws_acm_certificate.endpoint_cert.domain_validation_options.0.resource_record_value]
    ttl     = 60
}

resource "aws_acm_certificate_validation" "cert_validation" {
    provider                = aws.useast
    certificate_arn         = aws_acm_certificate.endpoint_cert.arn
    validation_record_fqdns = [aws_route53_record.endpoint_cert_validation.fqdn]
}

resource "aws_api_gateway_domain_name" "api_endpoint_domain" {
    certificate_arn = aws_acm_certificate_validation.cert_validation.certificate_arn
    domain_name     = var.endpoint
}

resource "aws_route53_record" "api_endpoint_domain_r53" {
    name    = aws_api_gateway_domain_name.api_endpoint_domain.domain_name
    type    = "A"
    zone_id = data.aws_route53_zone.root_zone.id

    alias {
        evaluate_target_health = true
        name                   = aws_api_gateway_domain_name.api_endpoint_domain.cloudfront_domain_name
        zone_id                = aws_api_gateway_domain_name.api_endpoint_domain.cloudfront_zone_id
    }
}

resource "aws_api_gateway_base_path_mapping" "api_endpoint_base_path_mapping" {
    api_id      = aws_api_gateway_rest_api.apigw.id
    stage_name  = aws_api_gateway_deployment.apigwdeploy.stage_name
    domain_name = aws_api_gateway_domain_name.api_endpoint_domain.domain_name
    base_path   = ""
}

resource "aws_dynamodb_table" "links_table" {
    name            = "UrlShortenerLinks_${var.env}"
    billing_mode    = "PAY_PER_REQUEST"
    hash_key        = "User_id"
    range_key       = "Link_id"

    attribute {
        name = "User_id"
        type = "S"
    }

    attribute {
        name = "Link_id"
        type = "S"
    }

    point_in_time_recovery {
        enabled = true
    }

    global_secondary_index {
        name               = "UrlLinkIdIndex"
        hash_key           = "Link_id"
        projection_type    = "INCLUDE"
        non_key_attributes = ["s_Url"]
  }
}

resource "aws_cognito_user_pool" "user_pool" {
    name = "UrlShortenerUserPool-${var.env}"

    admin_create_user_config {
        allow_admin_create_user_only = true
    }
}

resource "aws_cognito_user_pool_domain" "authdomain" {
    domain       = "${var.authdomain}-${var.env}"
    user_pool_id = aws_cognito_user_pool.user_pool.id
}

resource "aws_api_gateway_authorizer" "update_api_authoriser" {
    name            = "UrlShortenerApiAuthoriser-${var.env}"
    rest_api_id     = aws_api_gateway_rest_api.apigw.id
    type            = "COGNITO_USER_POOLS"
    provider_arns   = [aws_cognito_user_pool.user_pool.arn]
}

resource "aws_cognito_user_pool_client" "app_client" {
    name                            = "client"
    user_pool_id                    = aws_cognito_user_pool.user_pool.id
    generate_secret                 = true
    callback_urls                   = [
        "https://${var.env}.${var.root_domain}/_login",
        "http://localhost:3000/_login.html"
    ]
    supported_identity_providers    = ["COGNITO"]
    allowed_oauth_flows             = ["implicit"]
    allowed_oauth_scopes            = ["email", "openid"]
    allowed_oauth_flows_user_pool_client = true
}