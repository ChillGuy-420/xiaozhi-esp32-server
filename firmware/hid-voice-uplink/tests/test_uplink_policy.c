#include "uplink_policy.h"

#include <stdio.h>
#include <string.h>

static int failures = 0;

static void expect(const char *name, uplink_result_t got, uplink_result_t want) {
    if (got != want) {
        fprintf(stderr, "FAIL %s got %s want %s\n", name, uplink_result_name(got), uplink_result_name(want));
        ++failures;
    }
}

static const char *kCa =
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBTESTCERTIFICATEONLYFORPOLICYCHECKNOTAREALPRIVATEKEYMATERIAL\n"
    "-----END CERTIFICATE-----\n";

int main(void) {
    expect("empty", uplink_check("", "isolated-device-credential", kCa, strlen(kCa)), UPLINK_REJECT_EMPTY_ENDPOINT);
    expect("http", uplink_check("http://voice.example.test/hid-voice", "isolated-device-credential", kCa, strlen(kCa)),
           UPLINK_REJECT_INSECURE);
    expect("ntfy", uplink_check("https://ntfy.sh/topic", "isolated-device-credential", kCa, strlen(kCa)),
           UPLINK_REJECT_FORBIDDEN_HOST);
    expect("placeholder",
           uplink_check("https://PLACEHOLDER_NTFY_BASE/topic", "isolated-device-credential", kCa, strlen(kCa)),
           UPLINK_REJECT_FORBIDDEN_HOST);
    expect("tenclass", uplink_check("https://api.tenclass.net/xiaozhi/ota/", "isolated-device-credential", kCa, strlen(kCa)),
           UPLINK_REJECT_FORBIDDEN_HOST);
    expect("credential", uplink_check("https://voice.example.test/xiaozhi/isolated/hid-voice", "", kCa, strlen(kCa)),
           UPLINK_REJECT_CREDENTIAL);
    expect("ca", uplink_check("https://voice.example.test/xiaozhi/isolated/hid-voice", "isolated-device-credential",
                              "UNPROVISIONED\n", 14),
           UPLINK_REJECT_CA);
    expect("ok", uplink_check("https://voice.example.test/xiaozhi/isolated/hid-voice", "isolated-device-credential", kCa,
                              strlen(kCa)),
           UPLINK_OK);
    if (failures) {
        fprintf(stderr, "%d failures\n", failures);
        return 1;
    }
    puts("uplink policy ok");
    return 0;
}
