//! Shapes.

/// A shape with an area.
pub trait Shape {
    /// The area.
    fn area(&self) -> f64;
}

/// A circle.
pub struct Circle {
    /// The radius.
    pub radius: f64,
}

impl Shape for Circle {
    fn area(&self) -> f64 {
        std::f64::consts::PI * self.radius * self.radius
    }
}

/// A marker.
pub struct Unit;

/// A grid of `N` cells.
pub struct Grid<const N: usize> {
    /// The cells.
    pub cells: [u8; N],
}
