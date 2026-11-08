#ifndef ISOLATION_POLICY_H
#define ISOLATION_POLICY_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    ISO_OK = 0,
    ISO_REJECT_EMPTY_ENDPOINT,
    ISO_REJECT_PUBLIC_FALLBACK,
    ISO_REJECT_INSECURE_URL,
    ISO_REJECT_EMPTY_CREDENTIAL,
    ISO_REJECT_EMPTY_TOKEN,
    ISO_REJECT_MISSING_CA,
} iso_result_t;

typedef struct {
    const char *nvs_ota_url;
    const char *compiled_ota_url;
    const char *device_credential;
    const char *websocket_url;
    const char *websocket_token;
    const char *ca_pem;
    size_t ca_len;
} iso_input_t;

const char *iso_result_name(iso_result_t result);
iso_result_t iso_check_ca(const char *pem, size_t len);
iso_result_t iso_check_ota(const iso_input_t *in, const char **allowed_url);
iso_result_t iso_check_websocket(const iso_input_t *in);
int iso_use_public_bundle(void);
iso_result_t isolation_check_ota(const char *nvs_url, const char *compiled_url,
                                 const char *credential, const char **allowed_url);
iso_result_t isolation_check_websocket(const char *url, const char *token);

#ifdef __cplusplus
}
#endif

#endif
