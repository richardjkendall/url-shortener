variable "region" {
    description = "The AWS region to create things in."
    default     = "ap-southeast-2"
}

variable "root_domain" {
    description = "The Root 53 root domain where the application will be deployed"
}

variable "endpoint" {
    description = "The FQDN where the application will be deployed"
}

variable "env" {
    description = "The name of the environment"
}

variable "authdomain" {
    description = "Name of cognito domain for hosted UI"
}
