#include "isolation_policy.h"

#if defined(CONFIG_XIAOZHI_ISOLATED_PROFILE)

extern const unsigned char isolation_private_ca_pem_start[] asm("_binary_private_ca_pem_start");
extern const unsigned char isolation_private_ca_pem_end[] asm("_binary_private_ca_pem_end");

static void load_ca(iso_input_t *input) {
    input->ca_pem = reinterpret_cast<const char *>(isolation_private_ca_pem_start);
    input->ca_len = static_cast<size_t>(isolation_private_ca_pem_end - isolation_private_ca_pem_start);
}

extern "C" int isolation_private_ca(const unsigned char **buf, size_t *len) {
    iso_input_t input = {};
    load_ca(&input);
    if (iso_check_ca(input.ca_pem, input.ca_len) != ISO_OK || iso_use_public_bundle() != 0) {
        return 0;
    }
    if (buf == nullptr || len == nullptr) {
        return 0;
    }
    *buf = isolation_private_ca_pem_start;
    *len = input.ca_len;
    return 1;
}

extern "C" iso_result_t isolation_check_ota(const char *nvs_url, const char *compiled_url,
                                            const char *credential, const char **allowed_url) {
    iso_input_t input = {};
    input.nvs_ota_url = nvs_url;
    input.compiled_ota_url = compiled_url;
    input.device_credential = credential;
    load_ca(&input);
    return iso_check_ota(&input, allowed_url);
}

extern "C" iso_result_t isolation_check_websocket(const char *url, const char *token) {
    iso_input_t input = {};
    input.websocket_url = url;
    input.websocket_token = token;
    load_ca(&input);
    return iso_check_websocket(&input);
}

#endif
