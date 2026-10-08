import CoreGraphics
import Foundation

/// Canonical raw PDF CropBox coordinates. Does not replace PDFKit conversion.
public struct MnemosyneGeometry: Sendable {
    public let cropBox: CGRect
    public let rotation: Int
    public let userUnit: CGFloat

    public init(cropBox: CGRect, rotation: Int, userUnit: CGFloat = 1) throws {
        guard [0, 90, 180, 270].contains(rotation), userUnit.isFinite, userUnit > 0,
              cropBox.width > 0, cropBox.height > 0,
              [cropBox.minX, cropBox.minY, cropBox.maxX, cropBox.maxY].allSatisfy({ $0.isFinite })
        else { throw GeometryError.invalidGeometry }
        self.cropBox = cropBox
        self.rotation = rotation
        self.userUnit = userUnit
    }

    public enum GeometryError: Error { case invalidGeometry }

    public func viewportPoint(fromPDF point: CGPoint, scale: CGFloat, offset: CGPoint) -> CGPoint {
        let u = point.x - cropBox.minX, v = point.y - cropBox.minY
        let w = cropBox.width, h = cropBox.height
        let xy: CGPoint
        switch rotation {
        case 90: xy = CGPoint(x: v, y: u)
        case 180: xy = CGPoint(x: w-u, y: v)
        case 270: xy = CGPoint(x: h-v, y: w-u)
        default: xy = CGPoint(x: u, y: h-v)
        }
        return CGPoint(x: offset.x+xy.x*userUnit*scale, y: offset.y+xy.y*userUnit*scale)
    }

    public func pdfPoint(fromViewport point: CGPoint, scale: CGFloat, offset: CGPoint) -> CGPoint {
        let x = (point.x-offset.x)/(userUnit*scale), y = (point.y-offset.y)/(userUnit*scale)
        let w = cropBox.width, h = cropBox.height
        let uv: CGPoint
        switch rotation {
        case 90: uv = CGPoint(x: y, y: x)
        case 180: uv = CGPoint(x: w-x, y: y)
        case 270: uv = CGPoint(x: w-y, y: h-x)
        default: uv = CGPoint(x: x, y: h-y)
        }
        return CGPoint(x: cropBox.minX+uv.x, y: cropBox.minY+uv.y)
    }

    /// Maps a physical PDF point width to the current screen scale. Contract
    /// `width_pt` is physical points; raw content coordinates divide by
    /// `userUnit`, so this intentionally does not multiply by userUnit again.
    public func viewportWidth(fromPhysicalPoints width: CGFloat, scale: CGFloat) -> CGFloat {
        width * scale
    }

    public func physicalWidth(fromViewportWidth width: CGFloat, scale: CGFloat) -> CGFloat {
        width / scale
    }

    /// Computes the PDFKit scale needed to show a saved page-space viewport
    /// rectangle in the supplied view size. `viewport_rect` is unrotated PDF
    /// CropBox space, so its displayed width and height swap for quarter turns.
    public func scaleToFitPDFRect(_ pdfRect: CGRect, in viewportSize: CGSize) -> CGFloat? {
        guard [pdfRect.minX, pdfRect.minY, pdfRect.maxX, pdfRect.maxY,
               viewportSize.width, viewportSize.height].allSatisfy({ $0.isFinite }),
              pdfRect.width > 0, pdfRect.height > 0,
              viewportSize.width > 0, viewportSize.height > 0 else { return nil }
        let visibleRect = pdfRect.standardized.intersection(cropBox)
        guard !visibleRect.isNull, !visibleRect.isEmpty,
              visibleRect.width > 0, visibleRect.height > 0 else { return nil }
        let rotated = rotation == 90 || rotation == 270
        let displayWidth = (rotated ? visibleRect.height : visibleRect.width) * userUnit
        let displayHeight = (rotated ? visibleRect.width : visibleRect.height) * userUnit
        let scale = min(viewportSize.width / displayWidth, viewportSize.height / displayHeight)
        return scale.isFinite && scale > 0 ? scale : nil
    }

    /// Clips a raw, unrotated PDF-space polyline to the page CropBox. A path
    /// that leaves and re-enters the crop becomes separate polylines, keeping
    /// serialized web strokes inside the same canonical page boundary.
    public func clippedPolylines(_ points: [CGPoint]) -> [[CGPoint]] {
        guard let first = points.first else { return [] }
        guard points.count > 1 else { return contains(first) ? [[first]] : [] }

        var result: [[CGPoint]] = []
        var current: [CGPoint] = []
        for index in 0..<(points.count - 1) {
            let start = points[index]
            let end = points[index + 1]
            guard let clipped = clipSegment(from: start, to: end) else {
                if !current.isEmpty { result.append(current); current = [] }
                continue
            }
            if let last = current.last, nearlyEqual(last, clipped.0) {
                if !nearlyEqual(last, clipped.1) { current.append(clipped.1) }
            } else {
                if !current.isEmpty { result.append(current) }
                current = nearlyEqual(clipped.0, clipped.1) ? [clipped.0] : [clipped.0, clipped.1]
            }
            if !contains(end), !current.isEmpty {
                result.append(current)
                current = []
            }
        }
        if !current.isEmpty { result.append(current) }
        return result
    }

    public func contains(_ point: CGPoint) -> Bool {
        point.x.isFinite && point.y.isFinite &&
            point.x >= cropBox.minX && point.x <= cropBox.maxX &&
            point.y >= cropBox.minY && point.y <= cropBox.maxY
    }

    private func clipSegment(from start: CGPoint, to end: CGPoint) -> (CGPoint, CGPoint)? {
        guard [start.x, start.y, end.x, end.y].allSatisfy(\.isFinite) else { return nil }
        let dx = end.x - start.x
        let dy = end.y - start.y
        var t0: CGFloat = 0
        var t1: CGFloat = 1
        let constraints: [(CGFloat, CGFloat)] = [
            (-dx, start.x - cropBox.minX), (dx, cropBox.maxX - start.x),
            (-dy, start.y - cropBox.minY), (dy, cropBox.maxY - start.y)
        ]
        for (p, q) in constraints {
            if p == 0 {
                if q < 0 { return nil }
                continue
            }
            let ratio = q / p
            if p < 0 {
                if ratio > t1 { return nil }
                t0 = max(t0, ratio)
            } else {
                if ratio < t0 { return nil }
                t1 = min(t1, ratio)
            }
        }
        guard t0 <= t1 else { return nil }
        return (
            CGPoint(x: start.x + t0 * dx, y: start.y + t0 * dy),
            CGPoint(x: start.x + t1 * dx, y: start.y + t1 * dy)
        )
    }

    private func nearlyEqual(_ lhs: CGPoint, _ rhs: CGPoint) -> Bool {
        abs(lhs.x - rhs.x) < 1e-8 && abs(lhs.y - rhs.y) < 1e-8
    }
}
