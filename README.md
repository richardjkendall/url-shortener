# URL Shortener

Serverless app for a URL shortener + Terraform to deploy it

## Requirements
To use/deploy this, you need the following:

* an AWS account
* Python 3.6+
* nodejs 8+
* Terraform 0.12+
  
## What does it build
This app consists of:

* Lambda function to provide the API logic
  * The Lambda function code is in this repository, the terraform module packages this to a zip file for upload to Lambda
* DynamoDB table to store URLs and short codes
* API G/W to provide access to the API and to perform redirects for short URLs
* Cognito to provide user accounts
* CloudFront distribution to provide the hosting for the UI to manage the links and short codes
* S3 bucket to provide the origin for the CloudFront distribution
  * Content for UI is pulled from the richardjkendall/url-shortener-front-end repository, it is built and the build output is uploaded to the S3 bucket

## Required Variables
The Terraform module needs the following variables to deploy

|Variable|Description|Default|
|---|---|---|
|region|Which AWS region should the application be deployed in?  Note, this does not change where the ACM certificates are deployed, these always need to be in us-east-1|ap-southeast-2
|root_domain|The root of the domain where the application should be deployed e.g. example.com|n/a
|endpoint|The FQDN where the application will be deployed.  Can be an apex e.g. example.com|n/a
env|Name of the environment you are deploying e.g. test or production|n/a
authdomain|Name for the Cognito domain used for authentication|n/a

## How to deploy
1. Clone this repository
2. Create a file called ``terraform.tfvars`` in the root folder and add the variables defined above along with the values you want to use for them
3. Run ``terraform init`` then ``terraform plan`` and if you are happy with the output run ``terraform apply``

Note: I recommend using remote state management e.g. S3.  I use terragrunt to automate all this for me. 
