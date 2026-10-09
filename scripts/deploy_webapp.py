"""Phase 9: deploy the officer web app and protect it with Entra ID (Easy Auth).

Usage: python scripts/deploy_webapp.py            # deploy code + configure sign-in (idempotent)
       python scripts/deploy_webapp.py --code     # deploy code only

Steps
  1. zip webapp/ and deploy it (Oryx installs requirements on App Service)
  2. Entra app registration "grant-screening-officer-ui" (single tenant)
  3. client secret -> Key Vault only (never printed, never in the repo);
     the web app reads it through a Key Vault reference with its managed identity
  4. Easy Auth v2: unauthenticated requests are redirected to the Entra sign-in
  5. "assignment required": only users assigned to the app can sign in;
     the current az login user is assigned
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import grant_screening.azure_clients  # noqa: E402,F401  (loads .env)

AZ = shutil.which("az") or shutil.which("az.cmd")
RG = os.environ["AZURE_RESOURCE_GROUP"]
APP = os.environ["WEBAPP_NAME"]
VAULT = os.environ["KEY_VAULT_NAME"]
APP_REG = "grant-screening-officer-ui"
SECRET_NAME = "easyauth-client-secret"
SECRET_SETTING = "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET"


def az(*args: str, parse: bool = True):
    proc = subprocess.run([AZ, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        # never echo arguments: one of them may be a secret
        raise RuntimeError(f"az {args[0]} {args[1] if len(args) > 1 else ''} failed: {proc.stderr.strip()[:400]}")
    out = proc.stdout.strip()
    return json.loads(out) if parse and out else out


def deploy_code() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        archive = shutil.make_archive(str(Path(tmp) / "webapp"), "zip", ROOT / "webapp")
        print("deploying code (Oryx build on App Service, F1 can take a few minutes)...")
        az("webapp", "deploy", "-g", RG, "-n", APP, "--src-path", archive, "--type", "zip",
           "--track-status", "false", parse=False)


def configure_auth() -> str:
    host = az("webapp", "show", "-g", RG, "-n", APP, "--query", "defaultHostName", "-o", "tsv", parse=False)
    tenant = az("account", "show", "--query", "tenantId", "-o", "tsv", parse=False)
    redirect = f"https://{host}/.auth/login/aad/callback"

    existing = az("ad", "app", "list", "--display-name", APP_REG, "--query", "[0].appId", "-o", "tsv", parse=False)
    if existing:
        app_id = existing
        print(f"app registration exists: {app_id}")
    else:
        app_id = az("ad", "app", "create", "--display-name", APP_REG, "--sign-in-audience", "AzureADMyOrg",
                    "--web-redirect-uris", redirect, "--enable-id-token-issuance", "true",
                    "--query", "appId", "-o", "tsv", parse=False)
        print(f"created app registration: {app_id}")
    sp = az("ad", "sp", "list", "--filter", f"appId eq '{app_id}'", "--query", "[0].id", "-o", "tsv", parse=False)
    if not sp:
        sp = az("ad", "sp", "create", "--id", app_id, "--query", "id", "-o", "tsv", parse=False)

    # Secret straight from Entra into Key Vault: it never touches stdout or disk.
    # Idempotent: a new client secret is created only if Key Vault has none yet.
    has_secret = subprocess.run([AZ, "keyvault", "secret", "show", "--vault-name", VAULT, "--name", SECRET_NAME,
                                 "--query", "id", "-o", "tsv"], capture_output=True, text=True).returncode == 0
    if not has_secret:
        secret = az("ad", "app", "credential", "reset", "--id", app_id, "--display-name", "easyauth",
                    "--years", "1", "--append", "--query", "password", "-o", "tsv", parse=False)
        az("keyvault", "secret", "set", "--vault-name", VAULT, "--name", SECRET_NAME, "--value", secret,
           "--query", "id", "-o", "tsv", parse=False)
        del secret
    reference = f"@Microsoft.KeyVault(VaultName={VAULT};SecretName={SECRET_NAME})"
    # Pitfall: az treats an argument starting with "@" as "read from file", and cmd.exe
    # mangles ";" and "()". Passing the setting through a JSON file avoids both.
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump([{"name": SECRET_SETTING, "value": reference, "slotSetting": False}], f)
        settings_file = f.name
    try:
        az("webapp", "config", "appsettings", "set", "-g", RG, "-n", APP, "--settings", f"@{settings_file}",
           "-o", "none", parse=False)
    finally:
        os.unlink(settings_file)

    # New apps start on auth "v1" config; the v2 commands below need the upgrade first.
    version = az("webapp", "auth", "config-version", "show", "-g", RG, "-n", APP)
    if str(version.get("configVersion", "")).lower() != "v2":
        az("webapp", "auth", "config-version", "upgrade", "-g", RG, "-n", APP, "-o", "none", parse=False)
    az("webapp", "auth", "microsoft", "update", "-g", RG, "-n", APP, "--client-id", app_id,
       "--client-secret-setting-name", SECRET_SETTING,
       "--issuer", f"https://login.microsoftonline.com/{tenant}/v2.0", "--yes", "-o", "none", parse=False)
    az("webapp", "auth", "update", "-g", RG, "-n", APP, "--enabled", "true",
       "--unauthenticated-client-action", "RedirectToLoginPage", "--redirect-provider", "azureactivedirectory",
       "--excluded-paths", '["/healthz"]',  # health probe stays reachable; every page needs sign-in
       "-o", "none", parse=False)

    # Only assigned users may sign in; assign the current user (default access).
    az("ad", "sp", "update", "--id", sp, "--set", "appRoleAssignmentRequired=true", "-o", "none", parse=False)
    me = az("ad", "signed-in-user", "show", "--query", "id", "-o", "tsv", parse=False)
    assigned = az("rest", "--method", "get", "--url",
                  f"https://graph.microsoft.com/v1.0/servicePrincipals/{sp}/appRoleAssignedTo")
    if not any(a["principalId"] == me for a in assigned.get("value", [])):
        az("rest", "--method", "post", "--url", f"https://graph.microsoft.com/v1.0/servicePrincipals/{sp}/appRoleAssignedTo",
           "--body", json.dumps({"principalId": me, "resourceId": sp,
                                 "appRoleId": "00000000-0000-0000-0000-000000000000"}), "-o", "none", parse=False)
    return f"https://{host}"


def wait_for(url: str, path: str = "/", seconds: int = 600) -> int:
    deadline = time.time() + seconds
    code = 0
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url + path, method="GET")
            opener = urllib.request.build_opener(_NoRedirect())
            code = opener.open(req, timeout=30).status
        except urllib.error.HTTPError as exc:
            code = exc.code
        except Exception:  # noqa: BLE001 - still starting
            code = 0
        if code in (200, 302, 401):
            return code
        time.sleep(15)
    return code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


if __name__ == "__main__":
    deploy_code()
    url = f"https://{az('webapp', 'show', '-g', RG, '-n', APP, '--query', 'defaultHostName', '-o', 'tsv', parse=False)}"
    if "--code" not in sys.argv:
        url = configure_auth()
    code = wait_for(url)
    print(f"{url} -> HTTP {code} (302 = redirect to Entra sign-in, i.e. protected)")
