"""AWS unit prices per region (USD, on-demand, Linux, excluding tax).

Checked against AWS's public price list
(pricing.us-east-1.amazonaws.com/offers/v1.0/aws/...) on 2026-10-08, except
where marked. Override any rate, or add instance types, in config/cost.toml.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

PRICES_CHECKED = "2026-10-08"

# rate key -> description, used for validation and the report's price table
RATE_KEYS: dict[str, str] = {
    "ebs_gb_month": "EBS gp3 storage, per GB-month",
    "s3_standard_gb_month": "S3 Standard, per GB-month (first 50 TB)",
    "s3_glacier_ir_gb_month": "S3 Glacier Instant Retrieval, per GB-month",
    "s3_deep_archive_gb_month": "S3 Glacier Deep Archive, per GB-month",
    "s3_put_per_1000": "S3 PUT/COPY/POST/LIST, per 1,000",
    "s3_get_per_1000": "S3 GET and other, per 1,000",
    "transition_glacier_ir_per_1000": "Lifecycle transition to Glacier IR, per 1,000 objects",
    "transition_deep_archive_per_1000": "Lifecycle transition to Deep Archive, per 1,000 objects",
    "glacier_ir_retrieval_gb": "Glacier IR retrieval, per GB",
    "glue_dpu_hour": "Glue ETL job, per DPU-hour (0.308 on Glue 6.0+)",
    "public_ipv4_hour": "Public IPv4 address, per hour (AWS-wide rate; not in the regional file)",
    "nat_instance_month": "NAT instance, per month (from the WP3 cost-estimate doc)",
    "egress_gb": "Data transfer out to the internet, per GB (first 10 TB tier)",
}

_COMMON = {
    "s3_standard_gb_month": 0.023,
    "s3_glacier_ir_gb_month": 0.004,
    "s3_deep_archive_gb_month": 0.00099,
    "s3_put_per_1000": 0.005,
    "s3_get_per_1000": 0.0004,
    "transition_glacier_ir_per_1000": 0.02,
    "glacier_ir_retrieval_gb": 0.03,
    "glue_dpu_hour": 0.44,
    "public_ipv4_hour": 0.005,
    "nat_instance_month": 3.80,
    "egress_gb": 0.09,
}

# vm_hourly: on-demand Linux, shared tenancy, for the m7g / m7i / c7g / r7g /
# t4g families (medium to 4xlarge where offered). t4g is burstable: sustained
# load above its baseline incurs extra CPU-credit charges not modelled here.
PRICE_BOOK: dict[str, dict] = {
    "us-east-1": {
        "rates": {**_COMMON, "ebs_gb_month": 0.08, "transition_deep_archive_per_1000": 0.05},
        "vm_hourly": {
            "c7g.medium": 0.0363,
            "c7g.large": 0.0725,
            "c7g.xlarge": 0.145,
            "c7g.2xlarge": 0.29,
            "c7g.4xlarge": 0.58,
            "m7g.medium": 0.0408,
            "m7g.large": 0.0816,
            "m7g.xlarge": 0.1632,
            "m7g.2xlarge": 0.3264,
            "m7g.4xlarge": 0.6528,
            "m7i.large": 0.1008,
            "m7i.xlarge": 0.2016,
            "m7i.2xlarge": 0.4032,
            "m7i.4xlarge": 0.8064,
            "r7g.medium": 0.0536,
            "r7g.large": 0.1071,
            "r7g.xlarge": 0.2142,
            "r7g.2xlarge": 0.4284,
            "r7g.4xlarge": 0.8568,
            "t4g.medium": 0.0336,
            "t4g.large": 0.0672,
            "t4g.xlarge": 0.1344,
            "t4g.2xlarge": 0.2688,
        },
    },
    "eu-west-1": {
        "rates": {**_COMMON, "ebs_gb_month": 0.088, "transition_deep_archive_per_1000": 0.055},
        "vm_hourly": {
            "c7g.medium": 0.0388,
            "c7g.large": 0.0775,
            "c7g.xlarge": 0.155,
            "c7g.2xlarge": 0.3101,
            "c7g.4xlarge": 0.6202,
            "m7g.medium": 0.0455,
            "m7g.large": 0.091,
            "m7g.xlarge": 0.1819,
            "m7g.2xlarge": 0.3638,
            "m7g.4xlarge": 0.7276,
            "m7i.large": 0.11235,
            "m7i.xlarge": 0.2247,
            "m7i.2xlarge": 0.4494,
            "m7i.4xlarge": 0.8988,
            "r7g.medium": 0.0599,
            "r7g.large": 0.1199,
            "r7g.xlarge": 0.2397,
            "r7g.2xlarge": 0.4794,
            "r7g.4xlarge": 0.9588,
            "t4g.medium": 0.0368,
            "t4g.large": 0.0736,
            "t4g.xlarge": 0.1472,
            "t4g.2xlarge": 0.2944,
        },
    },
}


@dataclass(frozen=True)
class PriceBook:
    region: str
    rates: dict[str, float]
    vm_hourly: dict[str, float] = field(default_factory=dict)

    @classmethod
    def for_region(cls, region: str) -> "PriceBook":
        if region not in PRICE_BOOK:
            raise ValueError(f"no built-in prices for region {region!r}; choose one of: {', '.join(PRICE_BOOK)}")
        book = PRICE_BOOK[region]
        return cls(region, dict(book["rates"]), dict(book["vm_hourly"]))

    def override(self, **rates: float) -> "PriceBook":
        unknown = set(rates) - set(RATE_KEYS)
        if unknown:
            raise ValueError(f"unknown price key(s): {', '.join(sorted(unknown))}; known: {', '.join(RATE_KEYS)}")
        return dataclasses.replace(self, rates={**self.rates, **rates})

    def with_vm_prices(self, prices: dict[str, float]) -> "PriceBook":
        return dataclasses.replace(self, vm_hourly={**self.vm_hourly, **prices})

    def vm_rate(self, instance_type: str) -> float:
        if instance_type not in self.vm_hourly:
            raise ValueError(
                f"no {self.region} price for {instance_type}. Add it to config/cost.toml under "
                f'[prices.vm_hourly], e.g. "{instance_type}" = 0.20 (USD per hour). '
                f"Built in: {', '.join(sorted(self.vm_hourly))}"
            )
        return self.vm_hourly[instance_type]
