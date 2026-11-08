#include "isolation_policy.h"

#include <stdio.h>
#include <string.h>

static int failures = 0;

static void expect(const char *name, iso_result_t got, iso_result_t want) {
    if (got != want) {
        fprintf(stderr, "FAIL %s got %s want %s\n", name, iso_result_name(got), iso_result_name(want));
        ++failures;
    }
}

static const char *kCa =
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBTESTCERTIFICATEONLYFORPOLICYCHECKNOTAREALPRIVATEKEYMATERIAL\n"
    "-----END CERTIFICATE-----\n";

static iso_input_t base(void) {
    iso_input_t in;
    memset(&in, 0, sizeof(in));
    in.nvs_ota_url = "https://voice.example.test/xiaozhi/ota/";
    in.compiled_ota_url = "https://api.tenclass.net/xiaozhi/ota/";
    in.device_credential = "isolated-device-credential";
    in.websocket_url = "wss://voice.example.test/xiaozhi/v1/";
    in.websocket_token = "issued-token-value";
    in.ca_pem = kCa;
    in.ca_len = strlen(kCa);
    return in;
}

int main(void) {
    iso_input_t in;
    const char *allowed = "sentinel";

    in = base();
    in.nvs_ota_url = "";
    expect("empty nvs ignores compiled public url", iso_check_ota(&in, &allowed), ISO_REJECT_EMPTY_ENDPOINT);
    if (allowed != NULL) {
        fprintf(stderr, "FAIL compiled url was selected\n");
        ++failures;
    }

    in = base();
    in.nvs_ota_url = NULL;
    expect("null nvs", iso_check_ota(&in, NULL), ISO_REJECT_EMPTY_ENDPOINT);

    in = base();
    in.nvs_ota_url = "https://api.tenclass.net/xiaozhi/ota/";
    expect("public ota host", iso_check_ota(&in, NULL), ISO_REJECT_PUBLIC_FALLBACK);

    in = base();
    in.nvs_ota_url = "https://ota.tenclass.net/xiaozhi/ota/";
    expect("public ota subdomain", iso_check_ota(&in, NULL), ISO_REJECT_PUBLIC_FALLBACK);

    in = base();
    in.nvs_ota_url = "http://voice.example.test/xiaozhi/ota/";
    expect("plain http ota", iso_check_ota(&in, NULL), ISO_REJECT_INSECURE_URL);

    in = base();
    in.device_credential = "";
    expect("empty credential", iso_check_ota(&in, NULL), ISO_REJECT_EMPTY_CREDENTIAL);

    in = base();
    in.device_credential = "UNPROVISIONED";
    expect("placeholder credential", iso_check_ota(&in, NULL), ISO_REJECT_EMPTY_CREDENTIAL);

    in = base();
    in.device_credential = "short-secret";
    expect("short credential", iso_check_ota(&in, NULL), ISO_REJECT_EMPTY_CREDENTIAL);

    in = base();
    in.ca_pem = "UNPROVISIONED\n";
    in.ca_len = strlen(in.ca_pem);
    expect("placeholder ca", iso_check_ota(&in, NULL), ISO_REJECT_MISSING_CA);

    in = base();
    in.ca_pem = NULL;
    in.ca_len = 0;
    expect("missing ca", iso_check_ota(&in, NULL), ISO_REJECT_MISSING_CA);

    in = base();
    allowed = NULL;
    expect("provisioned ota", iso_check_ota(&in, &allowed), ISO_OK);
    if (allowed == NULL || strcmp(allowed, in.nvs_ota_url) != 0 || strcmp(allowed, in.compiled_ota_url) == 0) {
        fprintf(stderr, "FAIL allowed url is not the private nvs url\n");
        ++failures;
    }

    in = base();
    in.websocket_url = "";
    expect("empty websocket", iso_check_websocket(&in), ISO_REJECT_EMPTY_ENDPOINT);

    in = base();
    in.websocket_url = "ws://voice.example.test/xiaozhi/v1/";
    expect("plain ws", iso_check_websocket(&in), ISO_REJECT_INSECURE_URL);

    in = base();
    in.websocket_url = "wss://api.tenclass.net/xiaozhi/v1/";
    expect("public websocket", iso_check_websocket(&in), ISO_REJECT_PUBLIC_FALLBACK);

    in = base();
    in.websocket_token = "";
    expect("empty token", iso_check_websocket(&in), ISO_REJECT_EMPTY_TOKEN);

    in = base();
    in.ca_pem = "UNPROVISIONED\n";
    in.ca_len = strlen(in.ca_pem);
    expect("websocket without ca", iso_check_websocket(&in), ISO_REJECT_MISSING_CA);

    in = base();
    expect("provisioned websocket", iso_check_websocket(&in), ISO_OK);

    if (iso_use_public_bundle() != 0) {
        fprintf(stderr, "FAIL public bundle selected\n");
        ++failures;
    }

    if (failures != 0) {
        fprintf(stderr, "%d failures\n", failures);
        return 1;
    }
    puts("isolation policy ok");
    return 0;
}
