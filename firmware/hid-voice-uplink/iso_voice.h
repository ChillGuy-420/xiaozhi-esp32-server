#ifndef ISO_VOICE_H
#define ISO_VOICE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct iso_voice iso_voice_t;

typedef struct {
    void *ctx;
    /* Copy of the upload body is owned by the session until post returns. */
    int (*post_wav)(void *ctx, const uint8_t *wav, size_t len, uint8_t **resp, size_t *resp_len, int *http_status);
    /* Takes ownership of wav. Return 0 if queued, nonzero if the caller must free it. */
    int (*play_wav)(void *ctx, uint8_t *wav, size_t len);
    void (*cancel_play)(void *ctx);
    /* The capture buffer belongs to app_audio until this is called exactly once. */
    void (*release_capture)(void *ctx);
    void *(*alloc_fn)(size_t size);
    void (*free_fn)(void *ptr);
} iso_voice_ops_t;

iso_voice_t *iso_voice_create(const iso_voice_ops_t *ops, const char *https_url, const char *credential,
                              const char *ca_pem, size_t ca_len);
void iso_voice_destroy(iso_voice_t *voice);

/* capture_wav stays owned by the caller until release_capture. upload_wav is copied. */
int iso_voice_submit(iso_voice_t *voice, const uint8_t *capture_wav, size_t capture_len, const uint8_t *upload_wav,
                     size_t upload_len);
void iso_voice_cancel(iso_voice_t *voice);

int iso_voice_capture_releases(const iso_voice_t *voice);
int iso_voice_posts(const iso_voice_t *voice);
int iso_voice_plays(const iso_voice_t *voice);

#ifdef __cplusplus
}
#endif

#endif
