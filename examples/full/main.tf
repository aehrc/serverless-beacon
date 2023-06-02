module "serverless-beacon" {
  region = "us-east-1"
  source = "../.."
  common-tags = {
    stack       = "serverless-beacon"
    environment = "dev"
  }
  variants-bucket-prefix       = "sbeacon-variants-"
  metadata-bucket-prefix       = "sbeacon-metadata-"
  lambda-layers-bucket-prefix  = "sbeacon-lambda-layers-"
  beacon-id                    = "au.csiro.sbeacon"
  beacon-name                  = "CSIRO Serverless Beacon"
  beacon-api-version           = "v2.0.0"
  beacon-environment           = "dev"
  beacon-description           = "Serverless Beacon (sBeacon)"
  beacon-version               = "v0.1.0"
  beacon-welcome-url           = "https://bioinformatics.csiro.au/"
  beacon-alternative-url       = "https://bioinformatics.csiro.au/"
  beacon-create-datetime       = "2018-11-26H00:00:00Z"
  beacon-update-datetime       = "2023-03-16H00:00:00Z"
  beacon-handovers             = "[]"
  beacon-documentation-url     = "https://github.com/EGA-archive/beacon2-ri-api"
  beacon-default-granularity   = "boolean"
  beacon-uri                   = "https://beacon.csiro.au"
  organisation-id              = "CSIRO"
  organisation-name            = "CSIRO"
  beacon-org-description       = "CSIRO, Australia"
  beacon-org-address           = "AEHRC, Westmead NSW, Australia"
  beacon-org-welcome-url       = "https://beacon.csiro.au"
  beacon-org-contact-url       = "https://bioinformatics.csiro.au/get-in-touch/"
  beacon-org-logo-url          = "https://raw.githubusercontent.com/aehrc/terraform-aws-serverless-beacon/master/assets/logo-tile.png"
  beacon-service-type-group    = "au.csiro"
  beacon-service-type-artifact = "beacon"
  beacon-service-type-version  = "1.0"
  beacon-enable-auth           = true
  beacon-guest-username        = "guest@gmail.com"
  beacon-guest-password        = "guest1234"
  beacon-admin-username        = "admin@gmail.com"
  beacon-admin-password        = "admin1234"
}
