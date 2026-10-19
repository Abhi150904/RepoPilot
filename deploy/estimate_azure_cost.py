"""Read public retail rates; never authenticates or changes Azure resources."""
from __future__ import annotations

import argparse
import json
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen


def retail_items(filter_text: str) -> list[dict]:
    url = "https://prices.azure.com/api/retail/prices?" + urlencode({"$filter": filter_text})
    items = []
    while url:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "prices.azure.com":
            raise ValueError("Unexpected pricing pagination origin.")
        with urlopen(url, timeout=30) as response:
            page = json.load(response)
        items.extend(page["Items"])
        url = page.get("NextPageLink")
    return items


def rate(items: list[dict], *, product: str, meter: str) -> float:
    values = {float(item["retailPrice"]) for item in items
              if item["productName"] == product and item["meterName"] == meter
              and item["currencyCode"] == "USD" and item["type"] == "Consumption"}
    if len(values) != 1:
        raise ValueError(f"Expected one unambiguous USD retail rate for {product} / {meter}.")
    return values.pop()


def estimate(*, vm_hourly: float, disk_monthly: float, ip_hourly: float,
             months: float, runner_hours: float, public_ips: int, other_monthly: float,
             remaining_usd: float) -> dict:
    monthly = vm_hourly * (730 + runner_hours) + 2 * disk_monthly + public_ips * ip_hourly * 730 + other_monthly
    total = monthly * months
    return {"monthly_usd": round(monthly, 2), "period_usd": round(total, 2),
            "remaining_credit_usd_supplied_by_user": remaining_usd,
            "headroom_usd": round(remaining_usd - total, 2),
            "fits_with_15_percent_reserve": total * 1.15 <= remaining_usd}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remaining-usd", type=float, required=True)
    parser.add_argument("--months", type=float, default=4)
    parser.add_argument("--runner-hours-per-month", type=float, default=20)
    parser.add_argument("--public-ips", type=int, choices=[1, 2], default=2)
    parser.add_argument("--other-monthly-usd", type=float, required=True,
                        help="Allowance for disk transactions, diagnostics, traffic and other Azure resources.")
    args = parser.parse_args()
    numbers = [args.remaining_usd, args.months, args.runner_hours_per_month, args.other_monthly_usd]
    import math
    if any(not math.isfinite(value) or value < 0 for value in numbers) or args.months == 0:
        parser.error("All amounts must be finite/nonnegative and months must be positive.")
    region = "armRegionName eq 'centralindia' and priceType eq 'Consumption'"
    items = retail_items(region + " and armSkuName eq 'Standard_B2als_v2'")
    items += retail_items(region + " and ((serviceName eq 'Storage' and meterName eq 'E4 LRS Disk')"
                          " or (serviceName eq 'Virtual Network' and meterName eq 'Standard IPv4 Static Public IP'))")
    vm = rate(items, product="Virtual Machines Basv2 Series", meter="B2als v2")
    disk = rate(items, product="Standard SSD Managed Disks", meter="E4 LRS Disk")
    ip = rate(items, product="IP Addresses", meter="Standard IPv4 Static Public IP")
    print(json.dumps({"rates_usd": {"vm_hourly": vm, "disk_monthly": disk, "ip_hourly": ip},
                      **estimate(vm_hourly=vm, disk_monthly=disk, ip_hourly=ip,
                                 months=args.months, runner_hours=args.runner_hours_per_month,
                                 public_ips=args.public_ips, other_monthly=args.other_monthly_usd,
                                 remaining_usd=args.remaining_usd)}, indent=2))
    print("Estimate only, not a subscription balance check or spending cap. OpenAI is billed separately.")


if __name__ == "__main__":
    main()
