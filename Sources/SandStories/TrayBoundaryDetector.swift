import CoreVideo
import Foundation
import ImageIO
import simd

enum TrayBoundaryDetector {
    /// Detect four saturated “marker” blobs near image corners (normalized Vision coords: origin bottom-left).
    /// Returns corners ordered: top-left, top-right, bottom-right, bottom-left in **image** normalized space (x,y in 0...1, y up).
    /// - Note: Tuned for bright coloured corner markers; returns nil if confidence is low.
    static func detectCorners(
        pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation
    ) -> (corners: [[Double]], confidence: Double)? {
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        guard width > 32, height > 32 else { return nil }

        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else { return nil }
        let rowBytes = CVPixelBufferGetBytesPerRow(pixelBuffer)
        let format = CVPixelBufferGetPixelFormatType(pixelBuffer)

        // Common AR capture: 420f or BGRA — handle BGRA-like 4-byte pixels.
        guard format == kCVPixelFormatType_32BGRA || format == kCVPixelFormatType_32ARGB else {
            // TODO: add YUV path if needed for your device pipeline.
            return nil
        }

        let marginX = max(4, width / 10)
        let marginY = max(4, height / 10)

        func centroid(inRect minX: Int, maxX: Int, minY: Int, maxY: Int, saturationMin: Float) -> SIMD2<Float>? {
            var sum = SIMD2<Float>(0, 0)
            var w: Float = 0
            for y in minY..<maxY {
                let row = base.advanced(by: y * rowBytes).assumingMemoryBound(to: UInt8.self)
                for x in minX..<maxX {
                    let o = x * 4
                    let b = Float(row[o]) / 255
                    let g = Float(row[o + 1]) / 255
                    let r = Float(row[o + 2]) / 255
                    let v = max(r, max(g, b))
                    let mn = min(r, min(g, b))
                    let s = v > 0.001 ? (v - mn) / v : 0
                    if s >= saturationMin && v > 0.25 {
                        sum += SIMD2<Float>(Float(x) + 0.5, Float(y) + 0.5)
                        w += 1
                    }
                }
            }
            guard w > 8 else { return nil }
            return sum / w
        }

        let sat: Float = 0.35
        guard
            let tl = centroid(inRect: 0, maxX: marginX, minY: 0, maxY: marginY, saturationMin: sat),
            let tr = centroid(inRect: width - marginX, maxX: width, minY: 0, maxY: marginY, saturationMin: sat),
            let bl = centroid(inRect: 0, maxX: marginX, minY: height - marginY, maxY: height, saturationMin: sat),
            let br = centroid(inRect: width - marginX, maxX: width, minY: height - marginY, maxY: height, saturationMin: sat)
        else { return nil }

        // Normalized Vision space (bottom-left origin)
        func norm(_ p: SIMD2<Float>) -> SIMD2<Float> {
            SIMD2<Float>(p.x / Float(width), p.y / Float(height))
        }

        let nTL = norm(tl)
        let nTR = norm(tr)
        let nBR = norm(br)
        let nBL = norm(bl)

        let corners = [
            [Double(nTL.x), Double(nTL.y)],
            [Double(nTR.x), Double(nTR.y)],
            [Double(nBR.x), Double(nBR.y)],
            [Double(nBL.x), Double(nBL.y)]
        ]

        // Crude confidence: spread of corners (quadrilateral area proxy)
        let area = abs((nTR.x - nTL.x) * (nBL.y - nTL.y))
        let confidence = min(1, Double(area * 4))
        guard confidence > 0.05 else { return nil }

        _ = orientation // reserved for future orientation-aware sampling
        return (corners, confidence)
    }
}
