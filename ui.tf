locals {
  origin_id = join("-", ["access-identity", "ui", var.endpoint])
}

/*data "external" "ui_commit" {
  program = ["/bin/bash", "git ls-remote https://github.com/richardjkendall/url-shortener-front-end.git HEAD | awk '{ print $1}'"]
}*/

resource "null_resource" "ui_packager" {
  triggers = {
    //always_run = data.external.ui_commit.result
    always_run = uuid()
  }
  provisioner "local-exec" {
    command = "mkdir -p ${path.module}/ui_package"
  }
  provisioner "local-exec" {
    command = "find ${path.module}/ui_package -mindepth 1 -delete "
  }
  provisioner "local-exec" {
    command = "git clone https://github.com/richardjkendall/url-shortener-front-end.git ui_package/"
  }
  provisioner "local-exec" {
    working_dir = "${path.module}/ui_package/"
    command = "npm install"
  }
  provisioner "local-exec" {
    working_dir = "${path.module}/ui_package/"
    command = "npm run build"
  }
}

resource "null_resource" "ui_copy" {
  triggers = {
    //always_run = data.external.ui_commit.result
    always_run = uuid()
  }
  provisioner "local-exec" {
    working_dir = "${path.module}/ui_package/build"
    command = "aws s3 sync . s3://${aws_s3_bucket.ui_bucket.id}"
  }
  depends_on = [null_resource.ui_packager]
}

resource "aws_s3_bucket" "ui_bucket" {
  bucket        = "ui.${var.endpoint}"
  acl           = "private"
  force_destroy = true

  cors_rule {
    allowed_methods = ["HEAD", "GET", "PUT", "POST"]
    allowed_origins = ["https*"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag", "x-amz-meta-custom-header"]
  }
}

resource "aws_s3_bucket_public_access_block" "block_ui_bucket_pub_access" {
  bucket = "${aws_s3_bucket.ui_bucket.id}"

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_identity" "ui_origin_access_identity" {
  comment = local.origin_id
}

data "aws_iam_policy_document" "bucket_policy" {
  statement {
    effect    = "Allow"
    resources = ["arn:aws:s3:::${aws_s3_bucket.ui_bucket.bucket}/*"]
    actions   = ["s3:GetObject"]
    principals {
      identifiers = [aws_cloudfront_origin_access_identity.ui_origin_access_identity.iam_arn]
      type        = "AWS"
    }
  }

  statement {
    effect    = "Allow"
    resources = ["arn:aws:s3:::${aws_s3_bucket.ui_bucket.bucket}"]
    actions   = ["s3:ListBucket"]
    principals {
      type        = "AWS"
      identifiers = [aws_cloudfront_origin_access_identity.ui_origin_access_identity.iam_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "cf_origin_bucket_policy" {
  bucket = aws_s3_bucket.ui_bucket.id
  policy = data.aws_iam_policy_document.bucket_policy.json
}

resource "aws_cloudfront_distribution" "cdn" {
  aliases             = ["ui.${var.endpoint}"]
  is_ipv6_enabled     = true
  http_version        = "http2"
  default_root_object = "index.html"
  price_class         = "PriceClass_All"

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = local.origin_id
    forwarded_values {
      cookies {
        forward = "none"
      }
      headers      = ["Origin"]
      query_string = false
    }

    max_ttl                = 3600
    min_ttl                = 0
    default_ttl            = 60
    viewer_protocol_policy = "redirect-to-https"
  }

  enabled = true

  origin {
    origin_id   = local.origin_id
    domain_name = aws_s3_bucket.ui_bucket.bucket_domain_name
    s3_origin_config {
      origin_access_identity = aws_cloudfront_origin_access_identity.ui_origin_access_identity.cloudfront_access_identity_path
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    minimum_protocol_version = "TLSv1.2_2018"
    acm_certificate_arn      = aws_acm_certificate.ui_endpoint_cert.arn
    ssl_support_method       = "sni-only"
  }

  depends_on = [aws_acm_certificate_validation.cert_validation]
}

resource "aws_acm_certificate" "ui_endpoint_cert" {
  provider          = aws.useast
  domain_name       = "ui.${var.endpoint}"
  validation_method = "DNS"
}

resource "aws_route53_record" "ui_endpoint_cert_validation" {
  name    = "${aws_acm_certificate.ui_endpoint_cert.domain_validation_options.0.resource_record_name}"
  type    = "${aws_acm_certificate.ui_endpoint_cert.domain_validation_options.0.resource_record_type}"
  zone_id = "${data.aws_route53_zone.root_zone.id}"
  records = ["${aws_acm_certificate.ui_endpoint_cert.domain_validation_options.0.resource_record_value}"]
  ttl     = 60
}

resource "aws_acm_certificate_validation" "ui_cert_validation" {
  provider                = aws.useast
  certificate_arn         = "${aws_acm_certificate.ui_endpoint_cert.arn}"
  validation_record_fqdns = ["${aws_route53_record.ui_endpoint_cert_validation.fqdn}"]
}

resource "aws_route53_record" "cf_endpoint_domain_r53" {
  name    = "ui.${var.endpoint}"
  type    = "A"
  zone_id = "${data.aws_route53_zone.root_zone.id}"

  alias {
    evaluate_target_health = true
    name                   = "${aws_cloudfront_distribution.cdn.domain_name}"
    zone_id                = "${aws_cloudfront_distribution.cdn.hosted_zone_id}"
  }
}