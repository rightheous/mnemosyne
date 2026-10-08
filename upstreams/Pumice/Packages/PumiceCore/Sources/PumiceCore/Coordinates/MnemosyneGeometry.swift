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
}
