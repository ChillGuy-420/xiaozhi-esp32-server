#include "iso_voice.h"

#include "uplink_policy.h"

#include <stdlib.h>
#include <string.h>

struct iso_voice {
    iso_voice_ops_t ops;
    char *url;
    char *credential;
    char *ca;
    size_t ca_len;
    uint32_t generation;
    int releases;
    int posts;
    int plays;
    int posting;
};

static void *xalloc(const iso_voice_t *voice, size_t size) {
    return voice->ops.alloc_fn ? voice->ops.alloc_fn(size) : malloc(size);
}

static void xfree(const iso_voice_t *voice, void *ptr) {
    if (ptr == NULL) {
        return;
    }
    if (voice->ops.free_fn) {
        voice->ops.free_fn(ptr);
    } else {
        free(ptr);
    }
}

iso_voice_t *iso_voice_create(const iso_voice_ops_t *ops, const char *https_url, const char *credential,
                              const char *ca_pem, size_t ca_len) {
    iso_voice_t *voice = calloc(1, sizeof(*voice));
    if (voice == NULL || ops == NULL) {
        free(voice);
        return NULL;
    }
    voice->ops = *ops;
    if (https_url) {
        voice->url = strdup(https_url);
    }
    if (credential) {
        voice->credential = strdup(credential);
    }
    if (ca_pem && ca_len) {
        voice->ca = malloc(ca_len + 1);
        if (voice->ca) {
            memcpy(voice->ca, ca_pem, ca_len);
            voice->ca[ca_len] = '\0';
            voice->ca_len = ca_len;
        }
    }
    return voice;
}

void iso_voice_destroy(iso_voice_t *voice) {
    if (voice == NULL) {
        return;
    }
    free(voice->url);
    free(voice->credential);
    free(voice->ca);
    free(voice);
}

int iso_voice_submit(iso_voice_t *voice, const uint8_t *capture_wav, size_t capture_len, const uint8_t *upload_wav,
                     size_t upload_len) {
    uint32_t generation;
    uint8_t *owned = NULL;
    uint8_t *response = NULL;
    size_t response_len = 0;
    int status = 0;
    int post_rc;
    (void)capture_wav;
    (void)capture_len;
    if (voice == NULL || voice->ops.release_capture == NULL || voice->ops.post_wav == NULL ||
        voice->ops.play_wav == NULL) {
        return -1;
    }
    if (uplink_check(voice->url, voice->credential, voice->ca, voice->ca_len) != UPLINK_OK || upload_wav == NULL ||
        upload_len < 44) {
        voice->ops.release_capture(voice->ops.ctx);
        voice->releases += 1;
        return -1;
    }
    owned = xalloc(voice, upload_len);
    if (owned == NULL) {
        voice->ops.release_capture(voice->ops.ctx);
        voice->releases += 1;
        return -1;
    }
    memcpy(owned, upload_wav, upload_len);
    /* The microphone buffer is no longer ours. */
    voice->ops.release_capture(voice->ops.ctx);
    voice->releases += 1;
    generation = voice->generation;
    voice->posting = 1;
    post_rc = voice->ops.post_wav(voice->ops.ctx, owned, upload_len, &response, &response_len, &status);
    voice->posting = 0;
    voice->posts += 1;
    xfree(voice, owned);
    owned = NULL;
    if (generation != voice->generation) {
        xfree(voice, response);
        return -1;
    }
    if (post_rc != 0 || status != 200 || response == NULL || response_len < 44) {
        xfree(voice, response);
        return -1;
    }
    if (voice->ops.play_wav(voice->ops.ctx, response, response_len) != 0) {
        xfree(voice, response);
        return -1;
    }
    voice->plays += 1;
    return 0;
}

void iso_voice_cancel(iso_voice_t *voice) {
    if (voice == NULL) {
        return;
    }
    voice->generation += 1;
    if (voice->ops.cancel_play) {
        voice->ops.cancel_play(voice->ops.ctx);
    }
}

int iso_voice_capture_releases(const iso_voice_t *voice) {
    return voice ? voice->releases : 0;
}

int iso_voice_posts(const iso_voice_t *voice) {
    return voice ? voice->posts : 0;
}

int iso_voice_plays(const iso_voice_t *voice) {
    return voice ? voice->plays : 0;
}
