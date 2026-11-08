#ifndef UPLINK_POLICY_H
#define UPLINK_POLICY_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    UPLINK_OK = 0,
    UPLINK_REJECT_EMPTY_ENDPOINT,
    UPLINK_REJECT_INSECURE,
    UPLINK_REJECT_FORBIDDEN_HOST,
    UPLINK_REJECT_CREDENTIAL,
    UPLINK_REJECT_CA,
} uplink_result_t;

const char *uplink_result_name(uplink_result_t result);

/* The old ntfy URL and webhook are not fallbacks. Pass NULL for them. */
uplink_result_t uplink_check(const char *https_url, const char *credential, const char *ca_pem, size_t ca_len);

#ifdef __cplusplus
}
#endif

#endif
