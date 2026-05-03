import aws_cdk as cdk
from infra.stack import EdiAnomalyStack
app = cdk.App()
EdiAnomalyStack(app, "EdiAnomalyStack")
app.synth()
