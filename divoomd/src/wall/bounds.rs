//! wall/bounds.rs -- the wall's pixel extent derived from its slot configs.

use super::WallConfig;

/// The wall's overall pixel extent and grid unit, derived from the slot
/// configs: free-form when any slot carries a width, else an N x M grid.
pub(super) struct WallBounds {
    pub(super) min_x: i32,
    pub(super) min_y: i32,
    pub(super) total_width: i32,
    pub(super) total_height: i32,
    pub(super) grid_unit_size: i32,
}

impl WallBounds {
    pub(super) fn from_configs(configs: &[WallConfig]) -> Self {
        let grid_unit_size = configs.first().map_or(16, |c| c.size);
        if configs.iter().any(|c| c.width.is_some()) {
            let min_x = configs.iter().map(|c| c.x).min().unwrap_or(0);
            let min_y = configs.iter().map(|c| c.y).min().unwrap_or(0);
            let max_x = configs
                .iter()
                .map(|c| c.x + c.width.unwrap_or(120))
                .max()
                .unwrap_or(0);
            let max_y = configs
                .iter()
                .map(|c| c.y + c.height.unwrap_or(120))
                .max()
                .unwrap_or(0);
            return Self {
                min_x,
                min_y,
                total_width: max_x - min_x,
                total_height: max_y - min_y,
                grid_unit_size,
            };
        }
        let slots_across = configs.iter().map(|c| c.x + 1).max().unwrap_or(0);
        let slots_down = configs.iter().map(|c| c.y + 1).max().unwrap_or(0);
        Self {
            min_x: 0,
            min_y: 0,
            total_width: slots_across * grid_unit_size,
            total_height: slots_down * grid_unit_size,
            grid_unit_size,
        }
    }
}
