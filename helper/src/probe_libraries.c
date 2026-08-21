/*
 * Clean-room, freestanding Bionic no-camera loader probe.
 *
 * This deliberately avoids a C runtime startup object so the probe can be
 * built against the minimal AOSP Bionic linker/libc/libdl/libm set.
 */

typedef unsigned long size_t;

extern void *dlopen(const char *filename, int flags);
extern int dlclose(void *handle);
extern char *dlerror(void);
extern long write(int fd, const void *buffer, size_t count);
extern void _exit(int status) __attribute__((noreturn));

#define RTLD_NOW 2
#define RTLD_GLOBAL 0x100

static const char *const libraries[] = {
    "libTUTKGlobalAPIs.so",
    "libIOTCAPIs.so",
    "libAVAPIs.so",
    "libRDTAPIs.so",
    "libP2PTunnelAPIs.so",
};

static size_t text_length(const char *value) {
    size_t length = 0;
    while (value[length] != '\0') {
        length++;
    }
    return length;
}

static void write_text(int fd, const char *value) {
    size_t remaining = text_length(value);
    const char *cursor = value;
    while (remaining > 0) {
        long written = write(fd, cursor, remaining);
        if (written <= 0) {
            return;
        }
        cursor += written;
        remaining -= (size_t)written;
    }
}

static void write_json_string(const char *value) {
    const unsigned char *cursor = (const unsigned char *)value;
    write_text(1, "\"");
    for (; *cursor != '\0'; cursor++) {
        switch (*cursor) {
        case '\\':
            write_text(1, "\\\\");
            break;
        case '"':
            write_text(1, "\\\"");
            break;
        case '\n':
            write_text(1, "\\n");
            break;
        case '\r':
            write_text(1, "\\r");
            break;
        case '\t':
            write_text(1, "\\t");
            break;
        default: {
            char character[2] = {(char)*cursor, '\0'};
            if (*cursor >= 0x20) {
                write_text(1, character);
            }
            break;
        }
        }
    }
    write_text(1, "\"");
}

static int run_probe(void) {
    void *handles[sizeof(libraries) / sizeof(libraries[0])] = {0};
    int failures = 0;
    size_t index;

    for (index = 0; index < sizeof(libraries) / sizeof(libraries[0]); index++) {
        handles[index] = dlopen(libraries[index], RTLD_NOW | RTLD_GLOBAL);
        write_text(1, "{\"event\":\"library_probe\",\"library\":");
        write_json_string(libraries[index]);
        if (handles[index] != (void *)0) {
            write_text(1, ",\"ok\":true}\n");
        } else {
            const char *error = dlerror();
            write_text(1, ",\"ok\":false,\"error\":");
            write_json_string(
                error != (char *)0 ? error : "unknown dynamic loader error"
            );
            write_text(1, "}\n");
            failures++;
        }
    }

    for (index = sizeof(libraries) / sizeof(libraries[0]); index > 0; index--) {
        if (handles[index - 1] != (void *)0) {
            dlclose(handles[index - 1]);
        }
    }
    if (failures == 0) {
        write_text(
            1, "{\"event\":\"probe_complete\",\"ok\":true,\"failures\":0}\n"
        );
        return 0;
    }
    write_text(1, "{\"event\":\"probe_complete\",\"ok\":false,\"failures\":");
    {
        char count[2] = {(char)('0' + failures), '\0'};
        write_text(1, count);
    }
    write_text(1, "}\n");
    return 1;
}

void _start(void) {
    _exit(run_probe());
}
