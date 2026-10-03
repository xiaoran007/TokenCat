//! Small owned-string C boundary for the independent Swift application.
use crate::{model::CoreConfig, model::Query, Engine};
use serde::Serialize;
use std::cell::RefCell;
use std::ffi::{c_char, c_void, CStr, CString};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::Mutex;

thread_local! { static LAST_ERROR: RefCell<String> = const { RefCell::new(String::new()) }; }

fn owned_json<T: Serialize>(result: Result<T, String>) -> *mut c_char {
    let value = match result {
        Ok(data) => serde_json::json!({"ok": true, "data": data}),
        Err(error) => serde_json::json!({"ok": false, "error": error}),
    };
    // JSON escapes embedded NUL characters; this CString cannot contain NUL.
    CString::new(value.to_string())
        .expect("JSON is NUL-free")
        .into_raw()
}

unsafe fn input<'a>(pointer: *const c_char) -> Result<&'a str, String> {
    if pointer.is_null() {
        return Err("Missing JSON input".into());
    }
    CStr::from_ptr(pointer)
        .to_str()
        .map_err(|_| "JSON input is not UTF-8".into())
}

fn protect<T>(action: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
    catch_unwind(AssertUnwindSafe(action))
        .unwrap_or_else(|_| Err("Native engine operation failed".into()))
}

/// # Safety
/// config_json must point to a NUL-terminated UTF-8 string for this call.
#[no_mangle]
pub unsafe extern "C" fn tokencat_open(config_json: *const c_char) -> *mut c_void {
    match protect(|| {
        let config: CoreConfig =
            serde_json::from_str(input(config_json)?).map_err(|e| e.to_string())?;
        Engine::open(config)
    }) {
        Ok(engine) => Box::into_raw(Box::new(Mutex::new(engine))).cast(),
        Err(error) => {
            LAST_ERROR.with(|e| *e.borrow_mut() = error);
            std::ptr::null_mut()
        }
    }
}

unsafe fn with_engine<T>(
    handle: *mut c_void,
    action: impl FnOnce(&mut Engine) -> Result<T, String>,
) -> Result<T, String> {
    if handle.is_null() {
        return Err("Native engine is not open".into());
    }
    let mutex = &*handle.cast::<Mutex<Engine>>();
    let mut engine = mutex
        .lock()
        .map_err(|_| "Native engine lock is poisoned".to_string())?;
    action(&mut engine)
}

/// # Safety
/// handle must be a live handle returned by tokencat_open.
#[no_mangle]
pub unsafe extern "C" fn tokencat_scan(handle: *mut c_void) -> *mut c_char {
    owned_json(protect(|| with_engine(handle, |engine| engine.scan())))
}

/// # Safety
/// handle must be live and query_json must be a NUL-terminated UTF-8 string.
#[no_mangle]
pub unsafe extern "C" fn tokencat_query(
    handle: *mut c_void,
    query_json: *const c_char,
) -> *mut c_char {
    owned_json(protect(|| {
        let query: Query = serde_json::from_str(input(query_json)?).map_err(|e| e.to_string())?;
        with_engine(handle, |engine| engine.query(&query))
    }))
}

#[no_mangle]
pub extern "C" fn tokencat_last_error() -> *mut c_char {
    owned_json::<()>(Err(LAST_ERROR.with(|e| e.borrow().clone())))
}

/// Validate a downloaded snapshot before the app atomically selects it.
/// # Safety
/// Both arguments must be live NUL-terminated UTF-8 strings for this call.
#[no_mangle]
pub unsafe extern "C" fn tokencat_validate_catalog(
    catalog_json: *const c_char,
    retrieved_at: *const c_char,
) -> *mut c_char {
    owned_json(protect(|| {
        let catalog = crate::pricing::PricingCatalog::from_json(input(catalog_json)?, input(retrieved_at)?)?;
        Ok(serde_json::json!({"id":catalog.id,"model_count":catalog.models.len()}))
    }))
}

/// # Safety
/// pointer must be NULL or an unfreed string returned by this library.
#[no_mangle]
pub unsafe extern "C" fn tokencat_string_free(pointer: *mut c_char) {
    if !pointer.is_null() {
        drop(CString::from_raw(pointer));
    }
}

/// # Safety
/// handle must be NULL or a live handle with no concurrent calls in progress.
#[no_mangle]
pub unsafe extern "C" fn tokencat_close(handle: *mut c_void) {
    if !handle.is_null() {
        drop(Box::from_raw(handle.cast::<Mutex<Engine>>()));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invalid_config_is_an_owned_error_without_unwinding() {
        unsafe {
            assert!(tokencat_open(std::ptr::null()).is_null());
            let error = tokencat_last_error();
            let value: serde_json::Value =
                serde_json::from_str(CStr::from_ptr(error).to_str().unwrap()).unwrap();
            assert_eq!(value["ok"], false);
            assert_eq!(value["error"], "Missing JSON input");
            tokencat_string_free(error);
            let result = tokencat_scan(std::ptr::null_mut());
            assert!(CStr::from_ptr(result)
                .to_str()
                .unwrap()
                .contains("not open"));
            tokencat_string_free(result);
        }
    }
}
