use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
};
use std::sync::Mutex;
use tokencat_core::{
    model::{CoreConfig, Query},
    Engine,
};

/// Each Python client owns its engine; all access is serialized without holding the GIL.
#[pyclass(name = "Engine", module = "tokencat_native._native")]
struct PythonEngine {
    engine: Mutex<Option<Engine>>,
}

impl PythonEngine {
    fn with_engine<T>(&self, action: impl FnOnce(&mut Engine) -> Result<T, String>) -> PyResult<T> {
        let mut guard = self
            .engine
            .lock()
            .map_err(|_| PyRuntimeError::new_err("Native engine lock is poisoned"))?;
        let engine = guard
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("Native engine is closed"))?;
        action(engine).map_err(PyRuntimeError::new_err)
    }
}

#[pymethods]
impl PythonEngine {
    #[new]
    fn new(py: Python<'_>, config_json: &str) -> PyResult<Self> {
        let config: CoreConfig = serde_json::from_str(config_json)
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        let engine = py
            .detach(|| Engine::open(config))
            .map_err(PyRuntimeError::new_err)?;
        Ok(Self {
            engine: Mutex::new(Some(engine)),
        })
    }

    fn scan(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| {
            self.with_engine(|engine| {
                serde_json::to_string(&engine.scan()?).map_err(|error| error.to_string())
            })
        })
    }

    fn query(&self, py: Python<'_>, query_json: &str) -> PyResult<String> {
        let query: Query = serde_json::from_str(query_json)
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        py.detach(|| {
            self.with_engine(|engine| {
                serde_json::to_string(&engine.query(&query)?).map_err(|error| error.to_string())
            })
        })
    }

    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| {
            self.engine
                .lock()
                .map_err(|_| PyRuntimeError::new_err("Native engine lock is poisoned"))?
                .take();
            Ok(())
        })
    }
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PythonEngine>()?;
    Ok(())
}
