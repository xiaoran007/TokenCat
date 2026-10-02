#ifndef TOKENCAT_H
#define TOKENCAT_H
#ifdef __cplusplus
extern "C" {
#endif
/* All JSON strings are UTF-8. Returned strings are owned: call string_free. */
void *tokencat_open(const char *config_json);
char *tokencat_scan(void *handle);
char *tokencat_query(void *handle, const char *query_json);
char *tokencat_last_error(void);
void tokencat_string_free(char *pointer);
void tokencat_close(void *handle);
#ifdef __cplusplus
}
#endif
#endif
