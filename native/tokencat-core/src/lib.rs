pub mod collector;
pub mod ffi;
pub mod model;
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
        })
    }

    pub fn scan(&mut self) -> CoreResult<ScanReport> {
        collector::collect(&mut self.store, &self.config)
    }

    pub fn query(&self, query: &Query) -> CoreResult<Dashboard> {
        query::query_dashboard(&self.store, &self.catalog, query)
    }
}
