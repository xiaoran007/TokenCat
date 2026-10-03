pub mod collector;
pub mod antigravity;
pub mod ffi;
pub mod model;
pub mod opencode;
pub mod parsers;
pub mod pricing;
pub mod query;
pub mod store;

use model::{CoreConfig, CoreResult, Dashboard, Query, ScanReport};
use pricing::PricingCatalog;
use store::Store;

/// One engine belongs to one product process. No external daemon is required.
pub struct Engine {
    config: CoreConfig,
    store: Store,
    catalog: PricingCatalog,
    antigravity: antigravity::Cache,
}

impl Engine {
    pub fn open(config: CoreConfig) -> CoreResult<Self> {
        if let Some(parent) = config.database_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let catalog = PricingCatalog::load(config.pricing_path.as_deref())?;
        let store = Store::open(&config.database_path)?;
        Ok(Self {
            config,
            store,
            catalog,
            antigravity: antigravity::Cache::default(),
        })
    }

    pub fn scan(&mut self) -> CoreResult<ScanReport> {
        collector::collect_with_cache(&mut self.store, &self.config, &mut self.antigravity)
    }

    pub fn query(&self, query: &Query) -> CoreResult<Dashboard> {
        query::query_dashboard(&self.store, &self.catalog, query)
    }
}
