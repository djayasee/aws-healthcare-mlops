import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from edi_parser import parse_edi_837

SAMPLE_EDI = (
    "ISA*00*          *00*          *ZZ*SENDER*ZZ*RECEIVER*210101*1200*^*00501*000000001*0*P*:~\n"
    "GS*HC*SENDER*RECEIVER*20210101*1200*1*X*005010X222A1~\n"
    "ST*837*0001*005010X222A1~\n"
    "CLM*CLAIM001*500.00***11:B:1~\n"
    "DTP*431*D8*20240101~\n"
    "NM1*IL*1*SMITH*JOHN****MI*MEM00001~\n"
    "NM1*85*2*GENERAL*HOSPITAL****XX*1234567890~\n"
    "SV1*HC:99213*150.00*UN*1***I10~\n"
    "SE*9*0001~\n"
    "GE*1*1~\n"
    "IEA*1*000000001~\n"
)


def test_returns_list():
    result = parse_edi_837(SAMPLE_EDI)
    assert isinstance(result, list)


def test_one_claim_parsed():
    result = parse_edi_837(SAMPLE_EDI)
    assert len(result) == 1


def test_claim_id():
    result = parse_edi_837(SAMPLE_EDI)
    assert result[0]["claim_id"] == "CLAIM001"


def test_claim_amount():
    result = parse_edi_837(SAMPLE_EDI)
    assert result[0]["claim_amount"] == "500.00"


def test_patient_name():
    result = parse_edi_837(SAMPLE_EDI)
    assert result[0]["patient_last_name"] == "SMITH"
    assert result[0]["patient_first_name"] == "JOHN"


def test_provider_name():
    result = parse_edi_837(SAMPLE_EDI)
    assert result[0]["provider_last_name"] == "GENERAL"


def test_service_code():
    result = parse_edi_837(SAMPLE_EDI)
    assert result[0]["service_code"] == "99213"


def test_empty_input():
    result = parse_edi_837("")
    assert result == []
