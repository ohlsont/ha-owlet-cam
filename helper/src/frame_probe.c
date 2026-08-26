/*
 * Clean-room, freestanding Owlet/Kalay H.264 frame probe.
 *
 * Proprietary libraries and all camera secrets are user supplied at runtime.
 * Secrets enter only as one JSON object on stdin, are scrubbed before exit,
 * and are never written to stdout or stderr. Output contains safe JSON events.
 */

typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef unsigned int uint32_t;
typedef unsigned long size_t;
typedef long ssize_t;
typedef long time_t;

struct timespec {
    time_t tv_sec;
    long tv_nsec;
};

extern void *dlopen(const char *filename, int flags);
extern void *dlsym(void *handle, const char *symbol);
extern int dlclose(void *handle);
extern ssize_t read(int fd, void *buffer, size_t count);
extern ssize_t write(int fd, const void *buffer, size_t count);
extern int clock_gettime(int clock_id, struct timespec *value);
extern int getppid(void);
extern int prctl(int option, unsigned long arg2, unsigned long arg3,
                 unsigned long arg4, unsigned long arg5);
extern int usleep(unsigned int microseconds);
extern void _exit(int status) __attribute__((noreturn));
typedef void (*signal_handler_fn)(int);
extern signal_handler_fn signal(int signal_number, signal_handler_fn handler);

#define RTLD_NOW 2
#define RTLD_GLOBAL 0x100
#define CLOCK_MONOTONIC 1
#define INPUT_MAX 2048
#define FRAME_BUFFER_SIZE (4 * 1024 * 1024)
#define AUDIO_BUFFER_SIZE (64 * 1024)
#define FRAME_INFO_SIZE 28
#define CONNECT_INPUT_SIZE 160
#define AV_INPUT_SIZE 64
#define AV_OUTPUT_SIZE 32
#define IOCTRL_VIDEO_START 0x01ff
#define IOCTRL_AUDIO_START 0x0300
#define AV_ER_DATA_NOREADY -20012
#define AV_ER_LOSED_THIS_FRAME -20014
#define AV_ER_INCOMPLETE_FRAME -20013
#define SIGTERM 15
#define SIGINT 2
#define SIGPIPE 13
#define SIG_IGN ((signal_handler_fn)1)
#define PR_SET_PDEATHSIG 1
#ifdef STREAM_CAPTURE
#define EVENT_NAME "stream_capture"
#define CONTROL_FD 2
#elif defined(SNAPSHOT_CAPTURE)
#define EVENT_NAME "snapshot_capture"
#define CONTROL_FD 1
#else
#define EVENT_NAME "frame_probe"
#define CONTROL_FD 1
#endif

typedef int (*set_license_fn)(const char *key);
typedef int (*set_region_fn)(int region);
typedef int (*iotc_initialize2_fn)(uint32_t udp_port);
typedef int (*iotc_set_lan_search_port_fn)(uint32_t port);
typedef void (*iotc_setup_session_timeout_fn)(uint32_t timeout_seconds);
typedef int (*iotc_get_session_id_fn)(void);
typedef int (*iotc_connect_ex_fn)(const char *uid, int sid, void *input);
typedef int (*iotc_connect_stop_fn)(int sid);
struct session_info {
    uint8_t mode;
    char client_or_device;
    char uid[21];
    char remote_ip[17];
    unsigned short remote_port;
    uint32_t tx_packet_count;
    uint32_t rx_packet_count;
    uint32_t iotc_version;
    unsigned short vendor_id;
    unsigned short product_id;
    unsigned short group_id;
    uint8_t nat_type;
    uint8_t is_secure;
};
typedef char session_info_size_must_be_64[
    sizeof(struct session_info) == 64 ? 1 : -1
];
typedef int (*iotc_session_check_fn)(int sid, struct session_info *info);
typedef int (*iotc_session_close_fn)(int sid);
typedef int (*iotc_deinitialize_fn)(void);
typedef int (*av_initialize_fn)(int maximum_channels);
typedef int (*av_client_start_ex_fn)(void *input, void *output);
typedef int (*av_send_ioctrl_fn)(int av_index, uint32_t type,
                                 const char *data, int size);
typedef int (*av_recv_frame2_fn)(int av_index, char *frame_data,
                                 int frame_data_max, int *frame_data_size,
                                 int *frame_size, char *frame_info,
                                 int frame_info_max, int *frame_info_size,
                                 uint32_t *frame_number);
typedef int (*av_recv_audio_fn)(int av_index, char *frame_data,
                                int frame_data_max, char *frame_info,
                                int frame_info_max, uint32_t *frame_number);
typedef int (*av_client_stop_fn)(int av_index);
typedef int (*av_deinitialize_fn)(void);

struct api {
    set_license_fn set_license;
    set_region_fn set_region;
    iotc_initialize2_fn iotc_initialize2;
    iotc_set_lan_search_port_fn iotc_set_lan_search_port;
    iotc_setup_session_timeout_fn iotc_setup_session_timeout;
    iotc_get_session_id_fn iotc_get_session_id;
    iotc_connect_ex_fn iotc_connect_ex;
    iotc_connect_stop_fn iotc_connect_stop;
    iotc_session_check_fn iotc_session_check;
    iotc_session_close_fn iotc_session_close;
    iotc_deinitialize_fn iotc_deinitialize;
    av_initialize_fn av_initialize;
    av_client_start_ex_fn av_client_start_ex;
    av_send_ioctrl_fn av_send_ioctrl;
    av_recv_frame2_fn av_recv_frame2;
    av_recv_audio_fn av_recv_audio;
    av_client_stop_fn av_client_stop;
    av_deinitialize_fn av_deinitialize;
};

struct secrets {
    char sdk_key[520];
    char uid[128];
    char auth_key[32];
    char av_password[128];
#if defined(SNAPSHOT_CAPTURE) || defined(STREAM_CAPTURE)
    int output_fd;
#endif
#ifdef STREAM_CAPTURE
    int audio_enabled;
#endif
};

struct probe_stats {
    uint32_t frames;
    unsigned long bytes;
    uint32_t sps;
    uint32_t pps;
    uint32_t idr;
    uint32_t width;
    uint32_t height;
    unsigned long first_frame_ms;
    uint8_t session_mode;
#ifdef SNAPSHOT_CAPTURE
    unsigned long capture_bytes;
#endif
};

struct bit_reader {
    const uint8_t *data;
    size_t size;
    size_t bit;
};

static uint8_t frame_buffer[FRAME_BUFFER_SIZE];
static uint8_t audio_buffer[AUDIO_BUFFER_SIZE];
static uint8_t rbsp_buffer[4096];
#ifdef STREAM_CAPTURE
static volatile int stop_requested;

static void request_stop(int signal_number) {
    (void)signal_number;
    stop_requested = 1;
}
#endif

static int arm_parent_death_signal(void) {
    int parent = getppid();
    if (parent <= 1) return 0;
    if (prctl(PR_SET_PDEATHSIG, SIGTERM, 0, 0, 0) < 0) return 0;
    return getppid() == parent;
}

static size_t text_length(const char *value) {
    size_t length = 0;
    while (value[length] != '\0') {
        length++;
    }
    return length;
}

static void write_text(const char *value) {
    size_t remaining = text_length(value);
    const char *cursor = value;
    while (remaining > 0) {
        ssize_t written = write(CONTROL_FD, cursor, remaining);
        if (written <= 0) {
            return;
        }
        cursor += written;
        remaining -= (size_t)written;
    }
}

#if defined(SNAPSHOT_CAPTURE) || defined(STREAM_CAPTURE)
static int write_all_fd(int fd, const uint8_t *data, size_t size) {
    while (size > 0) {
        ssize_t written = write(fd, data, size);
        if (written <= 0) {
            return 0;
        }
        data += written;
        size -= (size_t)written;
    }
    return 1;
}
#endif

#ifdef STREAM_CAPTURE
static int write_stream_frame(const uint8_t *data, size_t size) {
    uint8_t header[4];
    if (size == 0 || size > FRAME_BUFFER_SIZE) return 0;
    header[0] = (uint8_t)(size >> 24);
    header[1] = (uint8_t)(size >> 16);
    header[2] = (uint8_t)(size >> 8);
    header[3] = (uint8_t)size;
    return write_all_fd(1, header, sizeof(header)) &&
           write_all_fd(1, data, size);
}

static int write_audio_frame(int fd, uint16_t codec_id, const uint8_t *data,
                             size_t size) {
    uint8_t header[8];
    if (size == 0 || size > AUDIO_BUFFER_SIZE) return 0;
    header[0] = (uint8_t)(size >> 24);
    header[1] = (uint8_t)(size >> 16);
    header[2] = (uint8_t)(size >> 8);
    header[3] = (uint8_t)size;
    header[4] = (uint8_t)(codec_id >> 8);
    header[5] = (uint8_t)codec_id;
    header[6] = 0;
    header[7] = 0;
    return write_all_fd(fd, header, sizeof(header)) &&
           write_all_fd(fd, data, size);
}
#endif

static void write_unsigned(unsigned long value) {
    char digits[32];
    size_t used = 0;
    if (value == 0) {
        write_text("0");
        return;
    }
    while (value > 0 && used < sizeof(digits)) {
        digits[used++] = (char)('0' + (value % 10));
        value /= 10;
    }
    while (used > 0) {
        write(CONTROL_FD, &digits[--used], 1);
    }
}

static void write_signed(int value) {
    unsigned int magnitude;
    if (value < 0) {
        write_text("-");
        magnitude = (unsigned int)(-(value + 1)) + 1;
    } else {
        magnitude = (unsigned int)value;
    }
    write_unsigned(magnitude);
}

static void scrub(void *pointer, size_t size) {
    volatile uint8_t *cursor = (volatile uint8_t *)pointer;
    while (size-- > 0) {
        *cursor++ = 0;
    }
}

static void zero_bytes(void *pointer, size_t size) {
    uint8_t *cursor = (uint8_t *)pointer;
    while (size-- > 0) {
        *cursor++ = 0;
    }
}

static void put_u32(void *pointer, uint32_t value) {
    uint8_t *bytes = (uint8_t *)pointer;
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
    bytes[2] = (uint8_t)(value >> 16);
    bytes[3] = (uint8_t)(value >> 24);
}

static void put_pointer(void *pointer, const void *value) {
    unsigned long raw = (unsigned long)value;
    uint8_t *bytes = (uint8_t *)pointer;
    size_t index;
    for (index = 0; index < sizeof(raw); index++) {
        bytes[index] = (uint8_t)(raw >> (index * 8));
    }
}

static unsigned long monotonic_ms(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        return 0;
    }
    return (unsigned long)now.tv_sec * 1000UL +
           (unsigned long)(now.tv_nsec / 1000000L);
}

static int hex_value(char value) {
    if (value >= '0' && value <= '9') {
        return value - '0';
    }
    if (value >= 'a' && value <= 'f') {
        return value - 'a' + 10;
    }
    if (value >= 'A' && value <= 'F') {
        return value - 'A' + 10;
    }
    return -1;
}

static int parse_json_string(const char *json, const char *key, char *output,
                             size_t output_size) {
    size_t json_length = text_length(json);
    size_t key_length = text_length(key);
    size_t index;
    for (index = 0; index + key_length + 3 < json_length; index++) {
        size_t key_index;
        if (json[index] != '"') {
            continue;
        }
        for (key_index = 0; key_index < key_length; key_index++) {
            if (json[index + 1 + key_index] != key[key_index]) {
                break;
            }
        }
        if (key_index != key_length ||
            json[index + key_length + 1] != '"') {
            continue;
        }
        index += key_length + 2;
        while (index < json_length &&
               (json[index] == ' ' || json[index] == '\t')) {
            index++;
        }
        if (index >= json_length || json[index++] != ':') {
            return 0;
        }
        while (index < json_length &&
               (json[index] == ' ' || json[index] == '\t')) {
            index++;
        }
        if (index >= json_length || json[index++] != '"') {
            return 0;
        }
        {
            size_t used = 0;
            while (index < json_length && json[index] != '"') {
                unsigned char decoded = (unsigned char)json[index++];
                if (decoded == '\\') {
                    int high;
                    int low;
                    if (index >= json_length) {
                        return 0;
                    }
                    decoded = (unsigned char)json[index++];
                    if (decoded == 'n') decoded = '\n';
                    else if (decoded == 'r') decoded = '\r';
                    else if (decoded == 't') decoded = '\t';
                    else if (decoded == 'u') {
                        if (index + 4 > json_length ||
                            json[index] != '0' || json[index + 1] != '0') {
                            return 0;
                        }
                        high = hex_value(json[index + 2]);
                        low = hex_value(json[index + 3]);
                        if (high < 0 || low < 0) {
                            return 0;
                        }
                        decoded = (unsigned char)((high << 4) | low);
                        index += 4;
                    } else if (decoded != '\\' && decoded != '"' &&
                               decoded != '/') {
                        return 0;
                    }
                }
                if (decoded == 0 || used + 1 >= output_size) {
                    return 0;
                }
                output[used++] = (char)decoded;
            }
            if (index >= json_length || used == 0) {
                return 0;
            }
            output[used] = '\0';
            return 1;
        }
    }
    return 0;
}

#if defined(SNAPSHOT_CAPTURE) || defined(STREAM_CAPTURE)
static int parse_output_fd(const char *value, int *output_fd) {
    unsigned int result = 0;
    size_t index = 0;
    if (value[0] == '\0') {
        return 0;
    }
    while (value[index] != '\0') {
        if (value[index] < '0' || value[index] > '9' || result > 104857U) {
            return 0;
        }
        result = result * 10U + (unsigned int)(value[index] - '0');
        index++;
    }
    if (result < 3 || result > 1048575U) {
        return 0;
    }
    *output_fd = (int)result;
    return 1;
}
#endif

static int read_secrets(struct secrets *values) {
    char input[INPUT_MAX];
    size_t used = 0;
    ssize_t received;
#if defined(SNAPSHOT_CAPTURE) || defined(STREAM_CAPTURE)
    char output_fd[16];
    zero_bytes(output_fd, sizeof(output_fd));
#endif
#ifdef STREAM_CAPTURE
    char audio_enabled[4];
    zero_bytes(audio_enabled, sizeof(audio_enabled));
#endif
    zero_bytes(input, sizeof(input));
    while (used + 1 < sizeof(input)) {
        received = read(0, input + used, sizeof(input) - used - 1);
        if (received < 0) {
            scrub(input, sizeof(input));
            return 0;
        }
        if (received == 0) {
            break;
        }
        used += (size_t)received;
        if (input[used - 1] == '\n') {
            break;
        }
    }
    input[used] = '\0';
    if (!parse_json_string(input, "sdk_key", values->sdk_key,
                           sizeof(values->sdk_key)) ||
        !parse_json_string(input, "uid", values->uid, sizeof(values->uid)) ||
        !parse_json_string(input, "auth_key", values->auth_key,
                           sizeof(values->auth_key)) ||
        !parse_json_string(input, "av_password", values->av_password,
                           sizeof(values->av_password))
#if defined(SNAPSHOT_CAPTURE) || defined(STREAM_CAPTURE)
        || !parse_json_string(input, "output_fd", output_fd,
                              sizeof(output_fd))
        || !parse_output_fd(output_fd, &values->output_fd)
#endif
#ifdef STREAM_CAPTURE
        || !parse_json_string(input, "audio_enabled", audio_enabled,
                              sizeof(audio_enabled))
        || (audio_enabled[0] != '0' && audio_enabled[0] != '1')
        || audio_enabled[1] != '\0'
#endif
    ) {
        scrub(input, sizeof(input));
#if defined(SNAPSHOT_CAPTURE) || defined(STREAM_CAPTURE)
        scrub(output_fd, sizeof(output_fd));
#endif
#ifdef STREAM_CAPTURE
        scrub(audio_enabled, sizeof(audio_enabled));
#endif
        return 0;
    }
#ifdef STREAM_CAPTURE
    values->audio_enabled = audio_enabled[0] == '1';
#endif
    scrub(input, sizeof(input));
#if defined(SNAPSHOT_CAPTURE) || defined(STREAM_CAPTURE)
    scrub(output_fd, sizeof(output_fd));
#endif
#ifdef STREAM_CAPTURE
    scrub(audio_enabled, sizeof(audio_enabled));
#endif
    return 1;
}

static int read_bit(struct bit_reader *reader, uint32_t *value) {
    if (reader->bit >= reader->size * 8) {
        return 0;
    }
    *value = (reader->data[reader->bit / 8] >> (7 - (reader->bit % 8))) & 1;
    reader->bit++;
    return 1;
}

static int read_bits(struct bit_reader *reader, uint32_t count,
                     uint32_t *value) {
    uint32_t result = 0;
    uint32_t bit;
    while (count-- > 0) {
        if (!read_bit(reader, &bit)) {
            return 0;
        }
        result = (result << 1) | bit;
    }
    *value = result;
    return 1;
}

static int read_ue(struct bit_reader *reader, uint32_t *value) {
    uint32_t leading = 0;
    uint32_t bit;
    uint32_t suffix = 0;
    while (1) {
        if (!read_bit(reader, &bit) || leading > 30) {
            return 0;
        }
        if (bit != 0) {
            break;
        }
        leading++;
    }
    if (leading != 0 && !read_bits(reader, leading, &suffix)) {
        return 0;
    }
    *value = ((1U << leading) - 1U) + suffix;
    return 1;
}

static int skip_scaling_list(struct bit_reader *reader, uint32_t size) {
    int last_scale = 8;
    int next_scale = 8;
    uint32_t index;
    for (index = 0; index < size; index++) {
        if (next_scale != 0) {
            uint32_t code;
            int delta;
            if (!read_ue(reader, &code)) {
                return 0;
            }
            delta = (code & 1U) ? (int)((code + 1U) / 2U)
                                : -(int)(code / 2U);
            next_scale = (last_scale + delta + 256) % 256;
        }
        if (next_scale != 0) {
            last_scale = next_scale;
        }
    }
    return 1;
}

static int parse_sps(const uint8_t *nal, size_t nal_size, uint32_t *width,
                     uint32_t *height) {
    size_t source;
    size_t rbsp_size = 0;
    uint32_t profile;
    uint32_t temporary;
    uint32_t chroma_format = 1;
    uint32_t separate_colour_plane = 0;
    uint32_t pic_width_mbs_minus1;
    uint32_t pic_height_map_units_minus1;
    uint32_t frame_mbs_only;
    uint32_t crop_flag;
    uint32_t crop_left = 0, crop_right = 0, crop_top = 0, crop_bottom = 0;
    uint32_t crop_unit_x = 1, crop_unit_y = 2;
    struct bit_reader reader;
    int zero_count = 0;
    if (nal_size < 4 || (nal[0] & 0x1f) != 7) {
        return 0;
    }
    for (source = 1; source < nal_size && rbsp_size < sizeof(rbsp_buffer);
         source++) {
        uint8_t value = nal[source];
        if (zero_count == 2 && value == 3) {
            zero_count = 0;
            continue;
        }
        rbsp_buffer[rbsp_size++] = value;
        zero_count = value == 0 ? zero_count + 1 : 0;
    }
    reader.data = rbsp_buffer;
    reader.size = rbsp_size;
    reader.bit = 0;
    if (!read_bits(&reader, 8, &profile) ||
        !read_bits(&reader, 8, &temporary) ||
        !read_bits(&reader, 8, &temporary) ||
        !read_ue(&reader, &temporary)) {
        return 0;
    }
    if (profile == 100 || profile == 110 || profile == 122 || profile == 244 ||
        profile == 44 || profile == 83 || profile == 86 || profile == 118 ||
        profile == 128 || profile == 138 || profile == 139 || profile == 134 ||
        profile == 135) {
        uint32_t scaling_matrix;
        if (!read_ue(&reader, &chroma_format)) return 0;
        if (chroma_format == 3 &&
            !read_bit(&reader, &separate_colour_plane)) return 0;
        if (!read_ue(&reader, &temporary) || !read_ue(&reader, &temporary) ||
            !read_bit(&reader, &temporary) ||
            !read_bit(&reader, &scaling_matrix)) return 0;
        if (scaling_matrix) {
            uint32_t index;
            uint32_t count = chroma_format != 3 ? 8 : 12;
            for (index = 0; index < count; index++) {
                uint32_t present;
                if (!read_bit(&reader, &present)) return 0;
                if (present && !skip_scaling_list(&reader, index < 6 ? 16 : 64))
                    return 0;
            }
        }
    }
    if (!read_ue(&reader, &temporary)) return 0;
    {
        uint32_t pic_order_cnt_type;
        if (!read_ue(&reader, &pic_order_cnt_type)) return 0;
        if (pic_order_cnt_type == 0) {
            if (!read_ue(&reader, &temporary)) return 0;
        } else if (pic_order_cnt_type == 1) {
            uint32_t cycle;
            uint32_t index;
            if (!read_bit(&reader, &temporary) ||
                !read_ue(&reader, &temporary) ||
                !read_ue(&reader, &temporary) ||
                !read_ue(&reader, &cycle)) return 0;
            for (index = 0; index < cycle; index++) {
                if (!read_ue(&reader, &temporary)) return 0;
            }
        }
    }
    if (!read_ue(&reader, &temporary) || !read_bit(&reader, &temporary) ||
        !read_ue(&reader, &pic_width_mbs_minus1) ||
        !read_ue(&reader, &pic_height_map_units_minus1) ||
        !read_bit(&reader, &frame_mbs_only)) return 0;
    if (!frame_mbs_only && !read_bit(&reader, &temporary)) return 0;
    if (!read_bit(&reader, &temporary) || !read_bit(&reader, &crop_flag))
        return 0;
    if (crop_flag &&
        (!read_ue(&reader, &crop_left) || !read_ue(&reader, &crop_right) ||
         !read_ue(&reader, &crop_top) || !read_ue(&reader, &crop_bottom)))
        return 0;
    if (!separate_colour_plane) {
        if (chroma_format == 1) {
            crop_unit_x = 2;
            crop_unit_y = 2 * (2 - frame_mbs_only);
        } else if (chroma_format == 2) {
            crop_unit_x = 2;
            crop_unit_y = 2 - frame_mbs_only;
        } else if (chroma_format == 3) {
            crop_unit_y = 2 - frame_mbs_only;
        }
    }
    *width = (pic_width_mbs_minus1 + 1) * 16 -
             (crop_left + crop_right) * crop_unit_x;
    *height = (pic_height_map_units_minus1 + 1) * 16 *
                  (2 - frame_mbs_only) -
              (crop_top + crop_bottom) * crop_unit_y;
    return *width >= 160 && *height >= 120 && *width <= 8192 && *height <= 8192;
}

static size_t start_code_size(const uint8_t *data, size_t size, size_t offset) {
    if (offset + 3 <= size && data[offset] == 0 && data[offset + 1] == 0 &&
        data[offset + 2] == 1) {
        return 3;
    }
    if (offset + 4 <= size && data[offset] == 0 && data[offset + 1] == 0 &&
        data[offset + 2] == 0 && data[offset + 3] == 1) {
        return 4;
    }
    return 0;
}

static uint32_t inspect_annex_b(const uint8_t *data, size_t size,
                                struct probe_stats *stats) {
    size_t offset = 0;
    uint32_t found = 0;
    while (offset < size) {
        size_t prefix = start_code_size(data, size, offset);
        size_t nal_start;
        size_t nal_end;
        uint8_t type;
        if (prefix == 0) {
            offset++;
            continue;
        }
        nal_start = offset + prefix;
        nal_end = nal_start;
        while (nal_end < size && start_code_size(data, size, nal_end) == 0) {
            nal_end++;
        }
        if (nal_start >= nal_end) {
            offset = nal_end;
            continue;
        }
        type = data[nal_start] & 0x1f;
        if (type == 7) {
            found |= 1U;
            stats->sps++;
            if (stats->width == 0) {
                parse_sps(data + nal_start, nal_end - nal_start, &stats->width,
                          &stats->height);
            }
        } else if (type == 8) {
            found |= 2U;
            stats->pps++;
        } else if (type == 5) {
            found |= 4U;
            stats->idr++;
        }
        offset = nal_end;
    }
    return found;
}

static void emit_error(const char *stage, int native_code) {
    write_text("{\"event\":\"");
    write_text(EVENT_NAME);
    write_text("\",\"ok\":false,\"stage\":\"");
    write_text(stage);
    write_text("\",\"native_code\":");
    write_signed(native_code);
    write_text("}\n");
}

static void emit_success(const struct probe_stats *stats,
                         unsigned long elapsed_ms) {
    unsigned long fps_milli = elapsed_ms > 0
                                  ? ((unsigned long)stats->frames * 1000000UL) /
                                        elapsed_ms
                                  : 0;
    write_text("{\"event\":\"");
    write_text(EVENT_NAME);
    write_text("\",\"ok\":true,\"frames\":");
    write_unsigned(stats->frames);
    write_text(",\"bytes\":");
    write_unsigned(stats->bytes);
    write_text(",\"sps\":");
    write_unsigned(stats->sps);
    write_text(",\"pps\":");
    write_unsigned(stats->pps);
    write_text(",\"idr\":");
    write_unsigned(stats->idr);
    write_text(",\"width\":");
    write_unsigned(stats->width);
    write_text(",\"height\":");
    write_unsigned(stats->height);
    write_text(",\"estimated_fps\":");
    write_unsigned(fps_milli / 1000);
    write_text(".");
    {
        unsigned long fraction = fps_milli % 1000;
        if (fraction < 100) write_text("0");
        if (fraction < 10) write_text("0");
        write_unsigned(fraction);
    }
    write_text(",\"first_frame_ms\":");
    write_unsigned(stats->first_frame_ms);
    write_text(",\"session_mode\":\"");
    if (stats->session_mode == 0)
        write_text("p2p");
    else if (stats->session_mode == 1)
        write_text("relay");
    else
        write_text("lan");
    write_text("\"");
#ifdef SNAPSHOT_CAPTURE
    write_text(",\"capture_bytes\":");
    write_unsigned(stats->capture_bytes);
#endif
    write_text(",\"clean_shutdown\":true}\n");
}

static int load_api(struct api *api, void **global_handle, void **iotc_handle,
                    void **av_handle, int audio_requested) {
    *global_handle = dlopen("libTUTKGlobalAPIs.so", RTLD_NOW | RTLD_GLOBAL);
    *iotc_handle = dlopen("libIOTCAPIs.so", RTLD_NOW | RTLD_GLOBAL);
    *av_handle = dlopen("libAVAPIs.so", RTLD_NOW | RTLD_GLOBAL);
    if (!*global_handle || !*iotc_handle || !*av_handle) return 0;
#define LOAD(target, handle, symbol)                                           \
    do {                                                                        \
        *(void **)(&(target)) = dlsym((handle), (symbol));                      \
        if (!(target)) return 0;                                                \
    } while (0)
    LOAD(api->set_license, *global_handle, "TUTK_SDK_Set_License_Key");
    LOAD(api->set_region, *global_handle, "TUTK_SDK_Set_Region");
    LOAD(api->iotc_initialize2, *iotc_handle, "IOTC_Initialize2");
    LOAD(api->iotc_set_lan_search_port, *iotc_handle,
         "IOTC_Set_LanSearchPort");
    LOAD(api->iotc_setup_session_timeout, *iotc_handle,
         "IOTC_Setup_Session_Alive_Timeout");
    LOAD(api->iotc_get_session_id, *iotc_handle, "IOTC_Get_SessionID");
    LOAD(api->iotc_connect_ex, *iotc_handle, "IOTC_Connect_ByUIDEx");
    LOAD(api->iotc_connect_stop, *iotc_handle, "IOTC_Connect_Stop_BySID");
    LOAD(api->iotc_session_check, *iotc_handle, "IOTC_Session_Check");
    LOAD(api->iotc_session_close, *iotc_handle, "IOTC_Session_Close");
    LOAD(api->iotc_deinitialize, *iotc_handle, "IOTC_DeInitialize");
    LOAD(api->av_initialize, *av_handle, "avInitialize");
    LOAD(api->av_client_start_ex, *av_handle, "avClientStartEx");
    LOAD(api->av_send_ioctrl, *av_handle, "avSendIOCtrl");
    LOAD(api->av_recv_frame2, *av_handle, "avRecvFrameData2");
    if (audio_requested) {
        LOAD(api->av_recv_audio, *av_handle, "avRecvAudioData");
    }
    LOAD(api->av_client_stop, *av_handle, "avClientStop");
    LOAD(api->av_deinitialize, *av_handle, "avDeInitialize");
#undef LOAD
    return 1;
}

static int run_probe(void) {
    struct secrets values;
    struct api api;
    struct probe_stats stats;
    void *global_handle = 0, *iotc_handle = 0, *av_handle = 0;
    uint8_t connect_input[CONNECT_INPUT_SIZE];
    uint8_t av_input[AV_INPUT_SIZE];
    uint8_t av_output[AV_OUTPUT_SIZE];
    struct session_info session;
    char frame_info[FRAME_INFO_SIZE];
    char audio_info[FRAME_INFO_SIZE];
    const char account[] = "admin";
    const char cipher[] = "DEFAULT:@SECLEVEL=0";
    char start_video[8] = {0};
    char start_audio[8] = {0};
    int iotc_initialized = 0, av_initialized = 0;
    int sid = -1, av_index = -1;
    int result = 1;
    int native_code = 0;
    unsigned long started_ms = monotonic_ms();
    unsigned long first_frame_started_ms = 0;
#ifdef STREAM_CAPTURE
    signal(SIGTERM, request_stop);
    signal(SIGINT, request_stop);
    signal(SIGPIPE, SIG_IGN);
#endif
    if (!arm_parent_death_signal()) {
        emit_error("parent_supervision", -1);
        return 1;
    }
    zero_bytes(&values, sizeof(values));
    zero_bytes(&api, sizeof(api));
    zero_bytes(&stats, sizeof(stats));
    zero_bytes(connect_input, sizeof(connect_input));
    zero_bytes(av_input, sizeof(av_input));
    zero_bytes(av_output, sizeof(av_output));
    zero_bytes(&session, sizeof(session));
    zero_bytes(frame_info, sizeof(frame_info));
    zero_bytes(audio_info, sizeof(audio_info));
    if (!read_secrets(&values)) {
        emit_error("invalid_input", -1);
        goto cleanup;
    }
    if (!load_api(&api, &global_handle, &iotc_handle, &av_handle,
#ifdef STREAM_CAPTURE
                  values.audio_enabled
#else
                  0
#endif
                  )) {
        emit_error("library_symbols", -1);
        goto cleanup;
    }
    native_code = api.set_license(values.sdk_key);
    if (native_code < 0) {
        emit_error("set_license", native_code);
        goto cleanup;
    }
    native_code = api.set_region(2);
    if (native_code < 0) {
        emit_error("set_region", native_code);
        goto cleanup;
    }
    native_code = api.iotc_set_lan_search_port(63616);
    if (native_code < 0) {
        emit_error("iotc_lan_search_port", native_code);
        goto cleanup;
    }
    api.iotc_setup_session_timeout(20);
    native_code = api.iotc_initialize2(0);
    if (native_code < 0) {
        emit_error("iotc_initialize", native_code);
        goto cleanup;
    }
    iotc_initialized = 1;
    native_code = api.av_initialize(512);
    if (native_code < 0) {
        emit_error("av_initialize", native_code);
        goto cleanup;
    }
    av_initialized = 1;
    sid = api.iotc_get_session_id();
    if (sid < 0) {
        emit_error("session_id", sid);
        goto cleanup;
    }
    put_u32(connect_input, CONNECT_INPUT_SIZE);
    put_u32(connect_input + 4, 0);
    {
        size_t length = text_length(values.auth_key);
        size_t index;
        if (length > 8) length = 8;
        for (index = 0; index < length; index++)
            connect_input[8 + index] = (uint8_t)values.auth_key[index];
    }
    put_u32(connect_input + 0x94, 20);
    connect_input[0x98] = 0;
    connect_input[0x9c] = 0;
    connect_input[0x9d] = 0;
    native_code = api.iotc_connect_ex(values.uid, sid, connect_input);
    if (native_code < 0) {
        emit_error("iotc_connect", native_code);
        goto cleanup;
    }
    sid = native_code;
    native_code = api.iotc_session_check(sid, &session);
    if (native_code < 0 || session.mode > 2) {
        emit_error("session_check", native_code < 0 ? native_code : -1);
        goto cleanup;
    }
    stats.session_mode = session.mode;
    put_u32(av_input, AV_INPUT_SIZE);
    put_u32(av_input + 4, (uint32_t)sid);
    av_input[8] = 0;
    put_u32(av_input + 0x0c, 20);
    put_pointer(av_input + 0x10, account);
    put_pointer(av_input + 0x18, values.av_password);
    put_u32(av_input + 0x20, 1);
    put_u32(av_input + 0x24, 2);
    put_u32(av_input + 0x28, 0);
    put_u32(av_input + 0x2c, 0);
    put_pointer(av_input + 0x30, cipher);
    put_u32(av_output, AV_OUTPUT_SIZE);
    av_index = api.av_client_start_ex(av_input, av_output);
    if (av_index < 0) {
        emit_error("av_authenticate", av_index);
        goto cleanup;
    }
    native_code = api.av_send_ioctrl(av_index, IOCTRL_VIDEO_START, start_video,
                                     sizeof(start_video));
    if (native_code < 0) {
        emit_error("start_video", native_code);
        goto cleanup;
    }
#ifdef STREAM_CAPTURE
    if (values.audio_enabled) {
        native_code = api.av_send_ioctrl(av_index, IOCTRL_AUDIO_START,
                                         start_audio, sizeof(start_audio));
        if (native_code < 0) {
            values.audio_enabled = 0;
        }
    }
#endif
    first_frame_started_ms = monotonic_ms();
#ifdef STREAM_CAPTURE
    while (!stop_requested) {
#else
    while (stats.frames < 100 && monotonic_ms() - first_frame_started_ms < 30000) {
#endif
        int data_size = 0, frame_size = 0, info_size = 0;
        uint32_t frame_number = 0;
        native_code = api.av_recv_frame2(
            av_index, (char *)frame_buffer, FRAME_BUFFER_SIZE, &data_size,
            &frame_size, frame_info, sizeof(frame_info), &info_size,
            &frame_number);
#ifdef STREAM_CAPTURE
        if (native_code >= 0) {
            if (data_size > 0 && data_size <= FRAME_BUFFER_SIZE) {
                if (stats.frames == 0)
                    stats.first_frame_ms = monotonic_ms() - first_frame_started_ms;
                stats.frames++;
                stats.bytes += (unsigned long)data_size;
                inspect_annex_b(frame_buffer, (size_t)data_size, &stats);
                if (!write_stream_frame(frame_buffer, (size_t)data_size)) {
                    emit_error("stream_output", -1);
                    goto cleanup;
                }
            }
        } else if (native_code != AV_ER_DATA_NOREADY &&
                   native_code != AV_ER_LOSED_THIS_FRAME &&
                   native_code != AV_ER_INCOMPLETE_FRAME) {
            emit_error("receive_frame", native_code);
            goto cleanup;
        }
        if (values.audio_enabled) {
            uint32_t audio_frame_number = 0;
            int audio_code = api.av_recv_audio(
                av_index, (char *)audio_buffer, AUDIO_BUFFER_SIZE, audio_info,
                sizeof(audio_info), &audio_frame_number);
            if (audio_code > 0 && audio_code <= AUDIO_BUFFER_SIZE) {
                uint16_t codec_id = (uint16_t)(uint8_t)audio_info[0] |
                                    ((uint16_t)(uint8_t)audio_info[1] << 8);
                if (!write_audio_frame(values.output_fd, codec_id, audio_buffer,
                                       (size_t)audio_code)) {
                    /* Audio failure is deliberately isolated from video. */
                    values.audio_enabled = 0;
                }
            } else if (audio_code < 0 && audio_code != AV_ER_DATA_NOREADY &&
                       audio_code != AV_ER_LOSED_THIS_FRAME &&
                       audio_code != AV_ER_INCOMPLETE_FRAME) {
                values.audio_enabled = 0;
            }
        }
        if (native_code == AV_ER_DATA_NOREADY) usleep(3000);
#else
        if (native_code >= 0) {
            if (data_size > 0 && data_size <= FRAME_BUFFER_SIZE) {
                if (stats.frames == 0)
                    stats.first_frame_ms = monotonic_ms() - first_frame_started_ms;
                stats.frames++;
                stats.bytes += (unsigned long)data_size;
                {
#ifdef STREAM_CAPTURE
                    inspect_annex_b(frame_buffer, (size_t)data_size, &stats);
                    if (!write_stream_frame(frame_buffer, (size_t)data_size)) {
                        emit_error("stream_output", -1);
                        goto cleanup;
                    }
#elif defined(SNAPSHOT_CAPTURE)
                    uint32_t nal_types =
                        inspect_annex_b(frame_buffer, (size_t)data_size, &stats);
                    if ((nal_types & 7U) == 7U) {
                        if (!write_all_fd(values.output_fd, frame_buffer,
                                          (size_t)data_size)) {
                            emit_error("capture_output", -1);
                            goto cleanup;
                        }
                        stats.capture_bytes = (unsigned long)data_size;
                        break;
                    }
#else
                    inspect_annex_b(frame_buffer, (size_t)data_size, &stats);
#endif
                }
            }
            continue;
        }
        if (native_code == AV_ER_DATA_NOREADY ||
            native_code == AV_ER_LOSED_THIS_FRAME ||
            native_code == AV_ER_INCOMPLETE_FRAME) {
            usleep(10000);
            continue;
        }
        emit_error("receive_frame", native_code);
        goto cleanup;
#endif
    }
#ifdef STREAM_CAPTURE
    if (stats.frames == 0) {
        emit_error("no_frame_timeout", native_code);
        goto cleanup;
    }
#else
#ifdef SNAPSHOT_CAPTURE
    if (stats.capture_bytes == 0) {
#else
    if (stats.frames < 100) {
#endif
        emit_error("no_frame_timeout", native_code);
        goto cleanup;
    }
#endif
    result = 0;

cleanup:
    if (av_index >= 0 && api.av_client_stop) api.av_client_stop(av_index);
    if (sid >= 0 && api.iotc_connect_stop) api.iotc_connect_stop(sid);
    if (sid >= 0 && api.iotc_session_close) api.iotc_session_close(sid);
    if (av_initialized && api.av_deinitialize) api.av_deinitialize();
    if (iotc_initialized && api.iotc_deinitialize) api.iotc_deinitialize();
    if (av_handle) dlclose(av_handle);
    if (iotc_handle) dlclose(iotc_handle);
    if (global_handle) dlclose(global_handle);
    scrub(&values, sizeof(values));
    scrub(connect_input, sizeof(connect_input));
    scrub(av_input, sizeof(av_input));
    scrub(av_output, sizeof(av_output));
    scrub(&session, sizeof(session));
    scrub(frame_info, sizeof(frame_info));
    scrub(audio_info, sizeof(audio_info));
    scrub(frame_buffer, sizeof(frame_buffer));
    scrub(audio_buffer, sizeof(audio_buffer));
    if (result == 0)
        emit_success(&stats, monotonic_ms() - started_ms);
    scrub(&stats, sizeof(stats));
    return result;
}

void _start(void) {
    _exit(run_probe());
}
