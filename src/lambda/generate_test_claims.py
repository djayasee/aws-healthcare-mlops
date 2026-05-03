import random
import json
import os

PROVIDERS = [
    {"npi": "1234567890", "last_name": "SMITH",  "first_name": "JOHN"},
    {"npi": "0987654321", "last_name": "PATEL",  "first_name": "PRIYA"},
    {"npi": "1122334455", "last_name": "GARCIA", "first_name": "MARIA"},
]

PATIENTS = [
    {"last_name": "JOHNSON", "first_name": "ALICE", "age_group": "31-45"},
    {"last_name": "LEE",     "first_name": "BRIAN", "age_group": "46-60"},
    {"last_name": "WILSON",  "first_name": "CAROL", "age_group": "61-75"},
    {"last_name": "BROWN",   "first_name": "DAVID", "age_group": "18-30"},
    {"last_name": "TAYLOR",  "first_name": "EVA",   "age_group": "76+"},
]

CPT_CODES = [
    {"code": "99213", "description": "Office visit moderate",       "typical_charge": 150.00},
    {"code": "99214", "description": "Office visit high complexity", "typical_charge": 220.00},
    {"code": "93000", "description": "Electrocardiogram",           "typical_charge": 75.00},
    {"code": "71046", "description": "Chest X-ray",                 "typical_charge": 180.00},
    {"code": "80053", "description": "Metabolic panel",             "typical_charge": 95.00},
    {"code": "99285", "description": "Emergency dept high",         "typical_charge": 850.00},
    {"code": "70553", "description": "MRI brain with contrast",     "typical_charge": 2200.00},
]

DIAGNOSIS_CODES = ["J18.9", "I10", "E11.9", "M54.5", "J06.9"]


def generate_edi_claim(claim_id, provider, patient, cpt, diagnosis, units=1, anomaly=False):
    charge = cpt["typical_charge"] * units
    if anomaly:
        charge = charge * random.uniform(5, 10)

    edi = (
        f"ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
        f"*210101*1200*^*00501*{claim_id:09d}*0*P*:~\n"
        f"GS*HC*SENDER*RECEIVER*20210101*1200*1*X*005010X222A1~\n"
        f"ST*837*0001*005010X222A1~\n"
        f"CLM*{claim_id}*{charge:.2f}***11:B:1~\n"
        f"DTP*431*D8*20240101~\n"
        f"NM1*IL*1*{patient['last_name']}*{patient['first_name']}****MI*MEM{claim_id:05d}~\n"
        f"NM1*85*2*{provider['last_name']}*{provider['first_name']}****XX*{provider['npi']}~\n"
        f"SV1*HC:{cpt['code']}*{charge:.2f}*UN*{units}***{diagnosis}~\n"
        f"SE*9*0001~\n"
        f"GE*1*1~\n"
        f"IEA*1*{claim_id:09d}~\n"
    )
    return edi, round(charge, 2)


def generate_all_claims(output_dir="test_data", num_claims=10):
    os.makedirs(output_dir, exist_ok=True)
    manifest = []

    for i in range(1, num_claims + 1):
        provider = random.choice(PROVIDERS)
        patient = random.choice(PATIENTS)
        cpt = random.choice(CPT_CODES)
        diagnosis = random.choice(DIAGNOSIS_CODES)
        units = random.randint(1, 3)
        anomaly = i in [3, 7]

        edi_text, charge = generate_edi_claim(
            claim_id=i,
            provider=provider,
            patient=patient,
            cpt=cpt,
            diagnosis=diagnosis,
            units=units,
            anomaly=anomaly,
        )

        filename = f"{output_dir}/claim_{i:03d}.edi"
        with open(filename, "w") as f:
            f.write(edi_text)

        manifest.append({
            "claim_id": i,
            "file": filename,
            "provider_npi": provider["npi"],
            "patient_age_group": patient["age_group"],
            "cpt_code": cpt["code"],
            "diagnosis_code": diagnosis,
            "units": units,
            "charge": charge,
            "is_anomaly": anomaly,
        })

    with open(f"{output_dir}/manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated {num_claims} claims in '{output_dir}/'")
    print(f"Anomalies: claims 3 and 7")


if __name__ == "__main__":
    generate_all_claims()
