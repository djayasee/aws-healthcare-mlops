import json
import os
import boto3

def parse_edi_837(edi_text):
    claims = []
    segments = edi_text.strip().split("~")

    claim = {}
    for segment in segments:
        elements = segment.strip().split("*")
        tag = elements[0]

        if tag == "CLM":
            cliam["claim_id"] = elements[1]
            claim["claim_amount"] = elements[2]

        elif tag == "NM1" and elements[1] =="IL":
            claim["patient_last_name"] = elements[3]
            claims["patient_first_nmame"] = elements[4]
        
        elif tag == "NM1" and elements[1] == "85":
            claim["provider_last_name"] = elements[3]
            claim["provider_first_name"] = elements[4]

        elif tag == "SV1":
            claim["service_code"] = elements[1].split(":")[1]
            claim["service_charge"] = elements[2]
            claims["service_units"] = elements[4]

        elif tag == "SE":
            if claim:
                claims.append(claim)
                claim = {}
            
    return claims
