"""Create or re-key the Dashboards server user. Never print passwords.

The name kibanaserver is kept because the security plugin's reserved
kibana_server role mapping already names it; harden-opensearch.py removed the
demo account with the public default password.
"""
from dotenv import dotenv_values

from engine import PRIVATE, engine_client


def provision_dashboards(engine):
    password = dotenv_values(PRIVATE / "dashboards.env").get("OPENSEARCH_DASHBOARDS_SERVER_PASSWORD")
    if not password:
        raise ValueError("Dashboards credentials are not configured")
    response = engine.put("/_plugins/_security/api/internalusers/kibanaserver",
                          json={"password": password})
    response.raise_for_status()
    mapping = engine.get("/_plugins/_security/api/rolesmapping/kibana_server")
    mapping.raise_for_status()
    if "kibanaserver" not in mapping.json()["kibana_server"]["users"]:
        raise ValueError("kibana_server role is not mapped to kibanaserver")


if __name__ == "__main__":
    with engine_client(admin=True) as engine:
        provision_dashboards(engine)
    print("Dashboards server user provisioned")
