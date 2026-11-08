#include "uplink_policy.h"

#include <ctype.h>
#include <string.h>
#include <strings.h>

static int blank(const char *value) {
    return value == NULL || value[0] == '\0';
}

static int starts_ci(const char *value, const char *prefix) {
    size_t i;
    for (i = 0; prefix[i] != '\0'; ++i) {
        if (value[i] == '\0' || tolower((unsigned char)value[i]) != tolower((unsigned char)prefix[i])) {
            return 0;
        }
    }
    return 1;
}

static int host_has(const char *url, const char *needle) {
    const char *host = strstr(url, "://");
    size_t length = 0;
    size_t i;
    if (host == NULL) {
        return 0;
    }
    host += 3;
    while (host[length] != '\0' && host[length] != '/' && host[length] != ':' && host[length] != '?' &&
           host[length] != '#') {
        ++length;
    }
    for (i = 0; i + strlen(needle) <= length; ++i) {
        if (strncasecmp(host + i, needle, strlen(needle)) == 0) {
            return 1;
        }
    }
    return 0;
}

static int memmem_local(const char *hay, size_t hay_len, const char *needle) {
    size_t needle_len = strlen(needle);
    size_t i;
    if (needle_len == 0 || hay_len < needle_len) {
        return 0;
    }
    for (i = 0; i + needle_len <= hay_len; ++i) {
        if (memcmp(hay + i, needle, needle_len) == 0) {
            return 1;
        }
    }
    return 0;
}

static int ca_ok(const char *pem, size_t len) {
    if (pem == NULL || len < 64) {
        return 0;
    }
    if (memmem_local(pem, len, "UNPROVISIONED")) {
        return 0;
    }
    return memmem_local(pem, len, "-----BEGIN CERTIFICATE-----") &&
           memmem_local(pem, len, "-----END CERTIFICATE-----");
}

const char *uplink_result_name(uplink_result_t result) {
    switch (result) {
        case UPLINK_OK:
            return "ok";
        case UPLINK_REJECT_EMPTY_ENDPOINT:
            return "empty_endpoint";
        case UPLINK_REJECT_INSECURE:
            return "insecure";
        case UPLINK_REJECT_FORBIDDEN_HOST:
            return "forbidden_host";
        case UPLINK_REJECT_CREDENTIAL:
            return "credential";
        case UPLINK_REJECT_CA:
            return "ca";
        default:
            return "rejected";
    }
}

uplink_result_t uplink_check(const char *https_url, const char *credential, const char *ca_pem, size_t ca_len) {
    size_t credential_len;
    if (blank(https_url)) {
        return UPLINK_REJECT_EMPTY_ENDPOINT;
    }
    if (!starts_ci(https_url, "https://")) {
        return UPLINK_REJECT_INSECURE;
    }
    if (host_has(https_url, "ntfy") || host_has(https_url, "tenclass") || host_has(https_url, "placeholder")) {
        return UPLINK_REJECT_FORBIDDEN_HOST;
    }
    if (blank(credential) || strcmp(credential, "UNPROVISIONED") == 0) {
        return UPLINK_REJECT_CREDENTIAL;
    }
    credential_len = strlen(credential);
    if (credential_len < 16 || credential_len > 128 || strstr(credential, "://") != NULL) {
        return UPLINK_REJECT_CREDENTIAL;
    }
    if (!ca_ok(ca_pem, ca_len)) {
        return UPLINK_REJECT_CA;
    }
    return UPLINK_OK;
}
