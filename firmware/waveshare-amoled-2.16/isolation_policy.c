#include "isolation_policy.h"

#include <ctype.h>
#include <string.h>
#include <strings.h>

static const void *find_bytes(const char *hay, size_t hay_len, const char *needle) {
    size_t needle_len = strlen(needle);
    if (needle_len == 0 || hay == NULL || hay_len < needle_len) {
        return NULL;
    }
    for (size_t i = 0; i + needle_len <= hay_len; ++i) {
        if (memcmp(hay + i, needle, needle_len) == 0) {
            return hay + i;
        }
    }
    return NULL;
}

static int is_blank(const char *value) {
    return value == NULL || value[0] == '\0';
}

static int starts_with_ci(const char *value, const char *prefix) {
    size_t i;
    if (value == NULL || prefix == NULL) {
        return 0;
    }
    for (i = 0; prefix[i] != '\0'; ++i) {
        if (value[i] == '\0' || tolower((unsigned char)value[i]) != tolower((unsigned char)prefix[i])) {
            return 0;
        }
    }
    return 1;
}

static const char *host_start(const char *url) {
    const char *mark = strstr(url, "://");
    const char *host;
    if (mark == NULL) {
        return NULL;
    }
    host = mark + 3;
    if (*host == '\0' || *host == '/' || *host == '?' || *host == '#') {
        return NULL;
    }
    return host;
}

static int host_is_public_fallback(const char *url) {
    const char *host = host_start(url);
    size_t length = 0;
    size_t suffix;
    if (host == NULL) {
        return 0;
    }
    while (host[length] != '\0' && host[length] != '/' && host[length] != ':' &&
           host[length] != '?' && host[length] != '#') {
        ++length;
    }
    suffix = strlen("tenclass.net");
    if (length == suffix || (length > suffix && host[length - suffix - 1] == '.')) {
        if (strncasecmp(host + length - suffix, "tenclass.net", suffix) == 0) {
            return 1;
        }
    }
    return 0;
}

static int credential_ok(const char *credential) {
    size_t length;
    if (is_blank(credential)) {
        return 0;
    }
    if (strcmp(credential, "UNPROVISIONED") == 0) {
        return 0;
    }
    length = strlen(credential);
    if (length < 16 || length > 128) {
        return 0;
    }
    if (strstr(credential, "://") != NULL) {
        return 0;
    }
    return 1;
}

const char *iso_result_name(iso_result_t result) {
    switch (result) {
        case ISO_OK:
            return "ok";
        case ISO_REJECT_EMPTY_ENDPOINT:
            return "empty_endpoint";
        case ISO_REJECT_PUBLIC_FALLBACK:
            return "public_fallback";
        case ISO_REJECT_INSECURE_URL:
            return "insecure_url";
        case ISO_REJECT_EMPTY_CREDENTIAL:
            return "empty_credential";
        case ISO_REJECT_EMPTY_TOKEN:
            return "empty_token";
        case ISO_REJECT_MISSING_CA:
            return "missing_ca";
        default:
            return "rejected";
    }
}

iso_result_t iso_check_ca(const char *pem, size_t len) {
    if (pem == NULL || len < 64) {
        return ISO_REJECT_MISSING_CA;
    }
    if (find_bytes(pem, len, "UNPROVISIONED") != NULL) {
        return ISO_REJECT_MISSING_CA;
    }
    if (find_bytes(pem, len, "-----BEGIN CERTIFICATE-----") == NULL ||
        find_bytes(pem, len, "-----END CERTIFICATE-----") == NULL) {
        return ISO_REJECT_MISSING_CA;
    }
    return ISO_OK;
}

iso_result_t iso_check_ota(const iso_input_t *in, const char **allowed_url) {
    iso_result_t ca;
    if (allowed_url != NULL) {
        *allowed_url = NULL;
    }
    if (in == NULL || is_blank(in->nvs_ota_url)) {
        return ISO_REJECT_EMPTY_ENDPOINT;
    }
    if (!starts_with_ci(in->nvs_ota_url, "https://") || host_start(in->nvs_ota_url) == NULL) {
        return ISO_REJECT_INSECURE_URL;
    }
    if (host_is_public_fallback(in->nvs_ota_url)) {
        return ISO_REJECT_PUBLIC_FALLBACK;
    }
    if (!credential_ok(in->device_credential)) {
        return ISO_REJECT_EMPTY_CREDENTIAL;
    }
    ca = iso_check_ca(in->ca_pem, in->ca_len);
    if (ca != ISO_OK) {
        return ca;
    }
    if (allowed_url != NULL) {
        *allowed_url = in->nvs_ota_url;
    }
    return ISO_OK;
}

iso_result_t iso_check_websocket(const iso_input_t *in) {
    iso_result_t ca;
    if (in == NULL || is_blank(in->websocket_url)) {
        return ISO_REJECT_EMPTY_ENDPOINT;
    }
    if (!starts_with_ci(in->websocket_url, "wss://") || host_start(in->websocket_url) == NULL) {
        return ISO_REJECT_INSECURE_URL;
    }
    if (host_is_public_fallback(in->websocket_url)) {
        return ISO_REJECT_PUBLIC_FALLBACK;
    }
    if (is_blank(in->websocket_token)) {
        return ISO_REJECT_EMPTY_TOKEN;
    }
    ca = iso_check_ca(in->ca_pem, in->ca_len);
    if (ca != ISO_OK) {
        return ca;
    }
    return ISO_OK;
}

int iso_use_public_bundle(void) {
    return 0;
}
