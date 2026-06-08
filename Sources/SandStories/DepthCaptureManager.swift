import ARKit
import CoreImage
import CoreVideo
import Dispatch
import Foundation
import ImageIO
import UniformTypeIdentifiers

struct DepthCaptureBenchmarkSnapshot: Sendable {
    var arFramesReceived: Int = 0
    var arFramesWithoutDepth: Int = 0
    var writerCaptureCalls: Int = 0
    var framesSkippedWriting: Int = 0
    var framesSkippedMotion: Int = 0
    var framesWritten: Int = 0
    var depthBytes: Int64 = 0
    var rgbBytes: Int64 = 0
    var totalDepthEncodeMilliseconds: Double = 0
    var totalRGBEncodeMilliseconds: Double = 0

    func summary(elapsedSeconds: TimeInterval) -> String {
        let seconds = max(elapsedSeconds, 0.001)
        let savedFPS = Double(framesWritten) / seconds
        let arFPS = Double(arFramesReceived) / seconds
        let totalMB = Double(depthBytes + rgbBytes) / 1_000_000
        let depthAvg = framesWritten > 0 ? totalDepthEncodeMilliseconds / Double(framesWritten) : 0
        let rgbAvg = framesWritten > 0 ? totalRGBEncodeMilliseconds / Double(framesWritten) : 0

        return "Benchmark \(Self.oneDecimal(seconds))s | AR \(Self.oneDecimal(arFPS)) fps | saved \(Self.oneDecimal(savedFPS)) fps (\(framesWritten) frames) | motion skips \(framesSkippedMotion) | no depth \(arFramesWithoutDepth) | depth \(Self.oneDecimal(depthAvg)) ms/frame | rgb \(Self.oneDecimal(rgbAvg)) ms/frame | \(Self.oneDecimal(totalMB)) MB"
    }

    private static func oneDecimal(_ value: Double) -> String {
        String(format: "%.1f", value)
    }
}

// Wraps a CVPixelBuffer so we can safely move it across Swift concurrency boundaries.
// We rely on ARC by holding a strong reference until encoding/writing completes.
final class PixelBufferBox: @unchecked Sendable {
    let pixelBuffer: CVPixelBuffer

    init(_ pixelBuffer: CVPixelBuffer) {
        self.pixelBuffer = pixelBuffer
    }
}

actor DepthCaptureWriter {
    private var isRecording: Bool = false
    private var isWriting: Bool = false

    private let maxDepthMeters: Float = 8.0
    private let ciContext: CIContext = CIContext()

    private var depthDirectory: URL?
    private var rgbDirectory: URL?
    private var sequentialIndex: Int = 0
    private var lastDownsample: [UInt16]?
    private var deltaThresholdMeanU16: Float = 400
    private var onSaved: (@Sendable (TimeInterval, String, String) async -> Void)?
    private var benchmarkMetrics = DepthCaptureBenchmarkSnapshot()

    func setRecording(_ isRecording: Bool) {
        self.isRecording = isRecording
    }

    func configure(
        depthDirectory: URL?,
        rgbDirectory: URL?,
        deltaThresholdMeanU16: Float,
        onSaved: (@Sendable (TimeInterval, String, String) async -> Void)?
    ) async {
        self.depthDirectory = depthDirectory
        self.rgbDirectory = rgbDirectory
        self.deltaThresholdMeanU16 = deltaThresholdMeanU16
        self.onSaved = onSaved
        sequentialIndex = 0
        lastDownsample = nil
    }

    func resetBenchmarkMetrics() {
        benchmarkMetrics = DepthCaptureBenchmarkSnapshot()
    }

    func benchmarkSnapshot() -> DepthCaptureBenchmarkSnapshot {
        benchmarkMetrics
    }

    func capture(
        timestamp: TimeInterval,
        depthMap: PixelBufferBox?,
        capturedImage: PixelBufferBox
    ) async {
        guard isRecording else { return }
        benchmarkMetrics.writerCaptureCalls += 1
        guard !isWriting else {
            benchmarkMetrics.framesSkippedWriting += 1
            return
        }
        guard let depthMap, let depthDirectory, let rgbDirectory, let onSaved else { return }

        isWriting = true
        defer { isWriting = false }

        do {
            let depthU16 = try Self.convertDepthToUInt16(
                depthMap.pixelBuffer,
                maxDepthMeters: maxDepthMeters
            )
            let width = CVPixelBufferGetWidth(depthMap.pixelBuffer)
            let height = CVPixelBufferGetHeight(depthMap.pixelBuffer)

            let down = Self.downsampleMean(depthU16, width: width, height: height, outW: 32, outH: 32)
            if let prev = lastDownsample {
                let meanAbs = Self.meanAbsoluteDifference(down, prev)
                if meanAbs < deltaThresholdMeanU16 {
                    benchmarkMetrics.framesSkippedMotion += 1
                    return
                }
            }
            lastDownsample = down

            sequentialIndex += 1
            let idx = sequentialIndex
            let depthName = String(format: "d_%06d.png", idx)
            let rgbName = String(format: "r_%06d.jpg", idx)
            let depthURL = depthDirectory.appendingPathComponent(depthName)
            let rgbURL = rgbDirectory.appendingPathComponent(rgbName)

            let depthStart = Self.nowMilliseconds()
            try writeDepthPNG(depthU16, width: width, height: height, to: depthURL)
            benchmarkMetrics.totalDepthEncodeMilliseconds += Self.nowMilliseconds() - depthStart

            let rgbStart = Self.nowMilliseconds()
            try writeRGBJPEG(from: capturedImage.pixelBuffer, to: rgbURL)
            benchmarkMetrics.totalRGBEncodeMilliseconds += Self.nowMilliseconds() - rgbStart
            benchmarkMetrics.framesWritten += 1
            benchmarkMetrics.depthBytes += Self.fileSize(at: depthURL)
            benchmarkMetrics.rgbBytes += Self.fileSize(at: rgbURL)

            let relDepth = "depth/\(depthName)"
            let relRgb = "rgb/\(rgbName)"
            await onSaved(timestamp, relDepth, relRgb)
        } catch {
            print("DepthCaptureWriter error: \(error)")
        }
    }

    private static func nowMilliseconds() -> Double {
        Double(DispatchTime.now().uptimeNanoseconds) / 1_000_000
    }

    private static func fileSize(at url: URL) -> Int64 {
        let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.int64Value
        return size ?? 0
    }

    private static func downsampleMean(_ src: [UInt16], width: Int, height: Int, outW: Int, outH: Int) -> [UInt16] {
        var out = [UInt16](repeating: 0, count: outW * outH)
        let bx = max(1, width / outW)
        let by = max(1, height / outH)
        for oy in 0..<outH {
            for ox in 0..<outW {
                let x0 = ox * bx
                let y0 = oy * by
                var sum: UInt32 = 0
                var n: UInt32 = 0
                for y in y0..<min(height, y0 + by) {
                    let row = y * width
                    for x in x0..<min(width, x0 + bx) {
                        sum += UInt32(src[row + x])
                        n += 1
                    }
                }
                out[oy * outW + ox] = n > 0 ? UInt16(min(UInt32(UInt16.max), sum / n)) : 0
            }
        }
        return out
    }

    private static func meanAbsoluteDifference(_ a: [UInt16], _ b: [UInt16]) -> Float {
        guard a.count == b.count, !a.isEmpty else { return Float.greatestFiniteMagnitude }
        var sum: UInt64 = 0
        for i in 0..<a.count {
            sum += UInt64(abs(Int32(a[i]) - Int32(b[i])))
        }
        return Float(sum) / Float(a.count)
    }

    private static func convertDepthToUInt16(_ depthMap: CVPixelBuffer, maxDepthMeters: Float) throws -> [UInt16] {
        let width = CVPixelBufferGetWidth(depthMap)
        let height = CVPixelBufferGetHeight(depthMap)
        let pixelFormat = CVPixelBufferGetPixelFormatType(depthMap)

        CVPixelBufferLockBaseAddress(depthMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }

        guard let baseAddress = CVPixelBufferGetBaseAddress(depthMap) else {
            throw NSError(domain: "DepthCaptureWriter", code: 1, userInfo: [NSLocalizedDescriptionKey: "Depth buffer has no base address"])
        }

        let rowBytes = CVPixelBufferGetBytesPerRow(depthMap)
        var depthU16 = [UInt16](repeating: 0, count: width * height)

        switch pixelFormat {
        case kCVPixelFormatType_DepthFloat32:
            let floatPtr = baseAddress.assumingMemoryBound(to: Float.self)
            let stride = rowBytes / MemoryLayout<Float>.size
            for y in 0..<height {
                let rowOffset = y * stride
                let outOffset = y * width
                for x in 0..<width {
                    depthU16[outOffset + x] = depthMetersToU16(floatPtr[rowOffset + x], maxDepthMeters: maxDepthMeters)
                }
            }
        case kCVPixelFormatType_DepthFloat16:
            let halfPtr = baseAddress.assumingMemoryBound(to: UInt16.self)
            let stride = rowBytes / MemoryLayout<UInt16>.size
            for y in 0..<height {
                let rowOffset = y * stride
                let outOffset = y * width
                for x in 0..<width {
                    let meters = Float(Float16(bitPattern: halfPtr[rowOffset + x]))
                    depthU16[outOffset + x] = depthMetersToU16(meters, maxDepthMeters: maxDepthMeters)
                }
            }
        default:
            throw NSError(domain: "DepthCaptureWriter", code: 2, userInfo: [NSLocalizedDescriptionKey: "Unsupported depth pixel format: \(pixelFormat)"])
        }
        return depthU16
    }

    private static func depthMetersToU16(_ meters: Float, maxDepthMeters: Float) -> UInt16 {
        guard meters.isFinite, meters > 0 else { return 0 }
        let clamped = min(max(meters, 0), maxDepthMeters)
        let normalized = clamped / maxDepthMeters
        return UInt16(normalized * Float(UInt16.max))
    }

    private func writeDepthPNG(_ depthU16: [UInt16], width: Int, height: Int, to url: URL) throws {
        let depthData = depthU16.withUnsafeBytes { Data($0) }
        guard let provider = CGDataProvider(data: depthData as CFData) else {
            throw NSError(domain: "DepthCaptureWriter", code: 3, userInfo: [NSLocalizedDescriptionKey: "Failed to create CGDataProvider for depth"])
        }

        let colorSpace = CGColorSpaceCreateDeviceGray()
        let bitmapInfo = CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue | CGBitmapInfo.byteOrder16Little.rawValue)

        guard let cgImage = CGImage(
            width: width,
            height: height,
            bitsPerComponent: 16,
            bitsPerPixel: 16,
            bytesPerRow: width * MemoryLayout<UInt16>.size,
            space: colorSpace,
            bitmapInfo: bitmapInfo,
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        ) else {
            throw NSError(domain: "DepthCaptureWriter", code: 4, userInfo: [NSLocalizedDescriptionKey: "Failed to create CGImage for depth"])
        }

        guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else {
            throw NSError(domain: "DepthCaptureWriter", code: 5, userInfo: [NSLocalizedDescriptionKey: "Failed to create CGImageDestination for depth PNG"])
        }

        let pngProps: [CFString: Any] = [
            kCGImagePropertyPNGCompressionFilter: 0,
            kCGImagePropertyPNGInterlaceType: 0
        ]
        let props: [CFString: Any] = [
            kCGImagePropertyPNGDictionary: pngProps
        ]
        CGImageDestinationAddImage(dest, cgImage, props as CFDictionary)
        guard CGImageDestinationFinalize(dest) else {
            throw NSError(domain: "DepthCaptureWriter", code: 6, userInfo: [NSLocalizedDescriptionKey: "Failed to finalize depth PNG"])
        }
    }

    private func writeRGBJPEG(from capturedImage: CVPixelBuffer, to url: URL) throws {
        let ciImage = CIImage(cvPixelBuffer: capturedImage)
        let extent = ciImage.extent

        guard let cgImage = ciContext.createCGImage(ciImage, from: extent) else {
            throw NSError(domain: "DepthCaptureWriter", code: 7, userInfo: [NSLocalizedDescriptionKey: "Failed to create CGImage from capturedImage"])
        }

        guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.jpeg.identifier as CFString, 1, nil) else {
            throw NSError(domain: "DepthCaptureWriter", code: 8, userInfo: [NSLocalizedDescriptionKey: "Failed to create CGImageDestination for JPEG"])
        }

        let jpegOptions: [CFString: Any] = [
            kCGImageDestinationLossyCompressionQuality: 0.88
        ]

        CGImageDestinationAddImage(dest, cgImage, jpegOptions as CFDictionary)
        guard CGImageDestinationFinalize(dest) else {
            throw NSError(domain: "DepthCaptureWriter", code: 9, userInfo: [NSLocalizedDescriptionKey: "Failed to finalize JPEG"])
        }
    }
}

// ARSessionDelegate implementation that forwards frame data to an actor for safe encoding/writing.
@MainActor
final class DepthCaptureManager: NSObject, ARSessionDelegate {
    private let writer = DepthCaptureWriter()
    private var isRecording: Bool = false
    private var captureInFlight: Bool = false
    private var benchmarkFramesReceived: Int = 0
    private var benchmarkFramesWithoutDepth: Int = 0

    var isCurrentlyRecording: Bool {
        return isRecording
    }

    func resetBenchmarkMetrics() async {
        resetBenchmarkFrameCounters()
        await writer.resetBenchmarkMetrics()
    }

    func benchmarkSnapshot() async -> DepthCaptureBenchmarkSnapshot {
        let writerSnapshot = await writer.benchmarkSnapshot()

        let counters = benchmarkFrameCounters()
        var snapshot = writerSnapshot
        snapshot.arFramesReceived = counters.received
        snapshot.arFramesWithoutDepth = counters.withoutDepth
        return snapshot
    }

    private func resetBenchmarkFrameCounters() {
        benchmarkFramesReceived = 0
        benchmarkFramesWithoutDepth = 0
    }

    private func benchmarkFrameCounters() -> (received: Int, withoutDepth: Int) {
        return (benchmarkFramesReceived, benchmarkFramesWithoutDepth)
    }

    func configureSessionCapture(
        depthDirectory: URL?,
        rgbDirectory: URL?,
        deltaThresholdMeanU16: Float,
        onSaved: (@Sendable (TimeInterval, String, String) async -> Void)?
    ) {
        let dd = depthDirectory
        let rd = rgbDirectory
        let th = deltaThresholdMeanU16
        let cb = onSaved
        Task {
            await writer.configure(
                depthDirectory: dd,
                rgbDirectory: rd,
                deltaThresholdMeanU16: th,
                onSaved: cb
            )
        }
    }

    func setRecording(_ isRecording: Bool) {
        self.isRecording = isRecording
        let writer = self.writer
        Task { await writer.setRecording(isRecording) }
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        let shouldCapture = isRecording
        if shouldCapture {
            benchmarkFramesReceived += 1
        }

        guard shouldCapture else { return }

        guard let depthData = frame.sceneDepth else {
            benchmarkFramesWithoutDepth += 1
            return
        }

        guard !captureInFlight else { return }
        captureInFlight = true

        let writer = self.writer
        let timestamp = frame.timestamp
        let depthMap = PixelBufferBox(depthData.depthMap)
        let capturedImage = PixelBufferBox(frame.capturedImage)

        Task {
            await writer.capture(
                timestamp: timestamp,
                depthMap: depthMap,
                capturedImage: capturedImage
            )
            self.captureInFlight = false
        }
    }
}
