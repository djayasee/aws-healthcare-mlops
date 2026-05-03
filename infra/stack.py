import aws_cdk as cdk
from aws_cdk import (
    Stack,aws_s3 as s3,
    aws_sqs as sqs,
    aws_kms as kms,
    aws_iam as iam,
    Duration,
    RemovalPolicy,
        )
from constructs import Construct

class EdiAnomalyStack(cdk.Stack):
    def __init__(self,scope:Construct,id:str,**kwargs):
        super().__init__(scope,id, **kwargs)
        self.encryption_key = kms.Key(
            self,
            "EdiEncryptionKey",
            description="KMS key for EDI Claims pipeline",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
            )
        self.raw_bucket = s3.Bucket(
            self,
            "RawEdiBucket",
            bucket_name=f"edi-raw-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.encryption_key,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.processed_bucket = s3.Bucket(
            self,
            "ProcessedEdiBucket",
            bucket_name=f"edi-processed-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.encryption_key,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.dlq = sqs.Queue(
            self,
            "EdiDlq",
            queue_name = "edi-anomaly-dlq",
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.encryption_key,
            retention_period=Duration.days(14),
        )

        self.queue = sqs.Queue(
            self,
            "EdiQueue",
            queue_name = "edi-anomaly-queue",
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=self.encryption_key,
            visibility_timeout=Duration.seconds(300),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.dlq,
            ),
        )
        self.parser_lambda_role = iam.Role(                                                                                                    self,
            "EdiParserLambdaRole",                                                                                               
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),                                                             
            managed_policies=[
                  iam.ManagedPolicy.from_aws_managed_policy_name(
                      "service-role/AWSLambdaBasicExecutionRole"
                  )
              ],
          )

        self.raw_bucket.grant_read(self.parser_lambda_role)
        self.processed_bucket.grant_write(self.parser_lambda_role)
        self.encryption_key.grant_encrypt_decrypt(self.parser_lambda_role)
        self.queue.grant_consume_messages(self.parser_lambda_role)

        self.anomaly_lambda_role = iam.Role(
              self,
              "AnomalyDetectorLambdaRole",
              assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
              managed_policies=[
                  iam.ManagedPolicy.from_aws_managed_policy_name(
                      "service-role/AWSLambdaBasicExecutionRole"
                  )
              ],
          )

        self.processed_bucket.grant_read(self.anomaly_lambda_role)
        self.encryption_key.grant_decrypt(self.anomaly_lambda_role)

        cdk.CfnOutput(self, "RawBucketName", value=self.raw_bucket.bucket_name)                                                            
        cdk.CfnOutput(self, "ProcessedBucketName", value=self.processed_bucket.bucket_name)
        cdk.CfnOutput(self, "QueueUrl", value=self.queue.queue_url)                                                              
        cdk.CfnOutput(self, "DlqUrl", value=self.dlq.queue_url)                                                                  
        cdk.CfnOutput(self, "KmsKeyArn", value=self.encryption_key.key_arn)