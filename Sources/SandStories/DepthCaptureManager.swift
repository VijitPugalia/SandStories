import ARKit
import AVFoundation
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
    private var confidenceDirectory: URL?
    private var streamsDirectory: URL?
    private var depthStreamHandle: FileHandle?
    private var smoothedDepthStreamHandle: FileHandle?
    private var confidenceStreamHandle: FileHandle?
    private var videoWriter: AVAssetWriter?
    private var videoInput: AVAssetWriterInput?
    private var videoAdaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var videoStartTimestamp: TimeInterval?
    private var sequentialIndex: Int = 0
    private var lastDownsample: [UInt16]?
    private var deltaThresholdMeanU16: Float = 400
    private var onSaved: (@Sendable (TimeInterval, String, String, String?, [Float]?, [Float]?) async -> Void)?
    private var onV2Saved: (@Sendable (V2StreamFrameRecord) async -> Void)?
    private var benchmarkMetrics = DepthCaptureBenchmarkSnapshot()

    func setRecording(_ isRecording: Bool) {
        self.isRecording = isRecording
    }

    func configure(
        depthDirectory: URL?,
        rgbDirectory: URL?,
        confidenceDirectory: URL?,
        streamsDirectory: URL?,
        deltaThresholdMeanU16: Float,
        onSaved: (@Sendable (TimeInterval, String, String, String?, [Float]?, [Float]?) async -> Void)?,
        onV2Saved: (@Sendable (V2StreamFrameRecord) async -> Void)?
    ) async {
        await finishRecording()
        self.depthDirectory = depthDirectory
        self.rgbDirectory = rgbDirectory
        self.confidenceDirectory = confidenceDirectory
        self.streamsDirectory = streamsDirectory
        self.deltaThresholdMeanU16 = deltaThresholdMeanU16
        self.onSaved = onSaved
        self.onV2Saved = onV2Saved
        sequentialIndex = 0
        lastDownsample = nil

        if let streamsDirectory {
            do {
                try FileManager.default.createDirectory(at: streamsDirectory, withIntermediateDirectories: true)
                depthStreamHandle = try Self.openStreamFile(streamsDirectory.appendingPathComponent("depth.f32"))
                smoothedDepthStreamHandle = try Self.openStreamFile(streamsDirectory.appendingPathComponent("smoothed_depth.f32"))
                confidenceStreamHandle = try Self.openStreamFile(streamsDirectory.appendingPathComponent("confidence.bin"))
            } catch {
                print("DepthCaptureWriter stream configure error: \(error)")
            }
        }
    }

    func resetBenchmarkMetrics() {
        benchmarkMetrics = DepthCaptureBenchmarkSnapshot()
    }

    func benchmarkSnapshot() -> DepthCaptureBenchmarkSnapshot {
        benchmarkMetrics
    }

    func finishRecording() async {
        try? depthStreamHandle?.close()
        try? smoothedDepthStreamHandle?.close()
        try? confidenceStreamHandle?.close()
        depthStreamHandle = nil
        smoothedDepthStreamHandle = nil
        confidenceStreamHandle = nil

        if let videoWriter, let videoInput {
            videoInput.markAsFinished()
            await withCheckedContinuation { continuation in
                videoWriter.finishWriting {
                    continuation.resume()
                }
            }
        }
        videoWriter = nil
        videoInput = nil
        videoAdaptor = nil
        videoStartTimestamp = nil
    }

    func capture(
        timestamp: TimeInterval,
        depthMap: PixelBufferBox?,
        smoothedDepthMap: PixelBufferBox?,
        confidenceMap: PixelBufferBox?,
        capturedImage: PixelBufferBox,
        cameraIntrinsics: simd_float3x3,
        cameraTransform: simd_float4x4
    ) async {
        guard isRecording else { return }
        benchmarkMetrics.writerCaptureCalls += 1
        guard !isWriting else {
            benchmarkMetrics.framesSkippedWriting += 1
            return
        }
        guard let depthMap else { return }

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
            if deltaThresholdMeanU16 > 0, let prev = lastDownsample {
                let meanAbs = Self.meanAbsoluteDifference(down, prev)
                if meanAbs < deltaThresholdMeanU16 {
                    benchmarkMetrics.framesSkippedMotion += 1
                    return
                }
            }
            lastDownsample = down

            sequentialIndex += 1
            let idx = sequentialIndex
            let depthStart = Self.nowMilliseconds()
            let depthValues = try Self.convertDepthToFloat32(depthMap.pixelBuffer)
            let depthData = depthValues.withUnsafeBytes { Data($0) }
            let depthOffset = try writeStreamData(depthData, to: depthStreamHandle)
            benchmarkMetrics.totalDepthEncodeMilliseconds += Self.nowMilliseconds() - depthStart
            benchmarkMetrics.depthBytes += Int64(depthData.count)

            var smoothedDepthOffset: UInt64?
            var smoothedDepthCount: Int?
            var smoothedDepthPixelFormat: String?
            if let smoothedDepthMap, let smoothedDepthStreamHandle {
                let smoothedValues = try Self.convertDepthToFloat32(smoothedDepthMap.pixelBuffer)
                let smoothedData = smoothedValues.withUnsafeBytes { Data($0) }
                smoothedDepthOffset = try writeStreamData(smoothedData, to: smoothedDepthStreamHandle)
                smoothedDepthCount = smoothedData.count
                smoothedDepthPixelFormat = Self.pixelFormatName(CVPixelBufferGetPixelFormatType(smoothedDepthMap.pixelBuffer))
                benchmarkMetrics.depthBytes += Int64(smoothedData.count)
            }

            var confidenceOffset: UInt64?
            var confidenceCount: Int?
            var confidencePixelFormat: String?
            var confidenceBytesPerRow: Int?
            if let confidenceMap, let confidenceStreamHandle {
                let confidenceData = try Self.rawPixelBufferBytes(confidenceMap.pixelBuffer)
                confidenceOffset = try writeStreamData(confidenceData, to: confidenceStreamHandle)
                confidenceCount = confidenceData.count
                confidencePixelFormat = Self.pixelFormatName(CVPixelBufferGetPixelFormatType(confidenceMap.pixelBuffer))
                confidenceBytesPerRow = CVPixelBufferGetBytesPerRow(confidenceMap.pixelBuffer)
            }

            let rgbStart = Self.nowMilliseconds()
            let rgbPTS = try appendVideoFrame(capturedImage.pixelBuffer, timestamp: timestamp)
            benchmarkMetrics.totalRGBEncodeMilliseconds += Self.nowMilliseconds() - rgbStart
            benchmarkMetrics.framesWritten += 1

            let intrinsicsArray = Self.intrinsicsToArray(cameraIntrinsics)
            let transformArray = Self.transformToArray(cameraTransform)
            if let onV2Saved {
                await onV2Saved(
                    .init(
                        frameIndex: idx,
                        arTimestamp: timestamp,
                        monotonicElapsedSeconds: 0,
                        width: width,
                        height: height,
                        sourceDepthPixelFormat: Self.pixelFormatName(CVPixelBufferGetPixelFormatType(depthMap.pixelBuffer)),
                        storedDepthFormat: "float32_little_endian_meters",
                        depthByteOffset: depthOffset,
                        depthByteCount: depthData.count,
                        smoothedDepthByteOffset: smoothedDepthOffset,
                        smoothedDepthByteCount: smoothedDepthCount,
                        smoothedDepthPixelFormat: smoothedDepthPixelFormat,
                        confidenceByteOffset: confidenceOffset,
                        confidenceByteCount: confidenceCount,
                        confidencePixelFormat: confidencePixelFormat,
                        confidenceBytesPerRow: confidenceBytesPerRow,
                        rgbPresentationTimeSeconds: rgbPTS,
                        cameraTransformColumnMajor: transformArray,
                        cameraIntrinsicsColumnMajor: intrinsicsArray,
                        cameraImageResolutionWidth: CVPixelBufferGetWidth(capturedImage.pixelBuffer),
                        cameraImageResolutionHeight: CVPixelBufferGetHeight(capturedImage.pixelBuffer)
                    )
                )
            }
        } catch {
            print("DepthCaptureWriter error: \(error)")
        }
    }

    private static func openStreamFile(_ url: URL) throws -> FileHandle {
        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }
        FileManager.default.createFile(atPath: url.path, contents: nil)
        return try FileHandle(forWritingTo: url)
    }

    private func writeStreamData(_ data: Data, to handle: FileHandle?) throws -> UInt64 {
        guard let handle else {
            throw NSError(domain: "DepthCaptureWriter", code: 20, userInfo: [NSLocalizedDescriptionKey: "Stream file is not open"])
        }
        let offset = try handle.offset()
        try handle.write(contentsOf: data)
        return offset
    }

    private func appendVideoFrame(_ pixelBuffer: CVPixelBuffer, timestamp: TimeInterval) throws -> Double? {
        guard let streamsDirectory else { return nil }
        if videoWriter == nil {
            try startVideoWriter(pixelBuffer: pixelBuffer, outputURL: streamsDirectory.appendingPathComponent("rgb.mp4"), timestamp: timestamp)
        }
        guard let videoInput, let videoAdaptor, videoInput.isReadyForMoreMediaData else { return nil }
        let start = videoStartTimestamp ?? timestamp
        let seconds = max(0, timestamp - start)
        let time = CMTime(seconds: seconds, preferredTimescale: 600)
        return videoAdaptor.append(pixelBuffer, withPresentationTime: time) ? seconds : nil
    }

    private func startVideoWriter(pixelBuffer: CVPixelBuffer, outputURL: URL, timestamp: TimeInterval) throws {
        if FileManager.default.fileExists(atPath: outputURL.path) {
            try FileManager.default.removeItem(at: outputURL)
        }
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
        let input = AVAssetWriterInput(
            mediaType: .video,
            outputSettings: [
                AVVideoCodecKey: AVVideoCodecType.h264,
                AVVideoWidthKey: width,
                AVVideoHeightKey: height,
                AVVideoCompressionPropertiesKey: [
                    AVVideoAverageBitRateKey: 2_000_000,
                    AVVideoMaxKeyFrameIntervalKey: 30
                ]
            ]
        )
        input.expectsMediaDataInRealTime = true
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: nil)
        guard writer.canAdd(input) else {
            throw NSError(domain: "DepthCaptureWriter", code: 21, userInfo: [NSLocalizedDescriptionKey: "Cannot add video input"])
        }
        writer.add(input)
        guard writer.startWriting() else {
            throw writer.error ?? NSError(domain: "DepthCaptureWriter", code: 22, userInfo: [NSLocalizedDescriptionKey: "Video writer failed to start"])
        }
        writer.startSession(atSourceTime: .zero)
        videoWriter = writer
        videoInput = input
        videoAdaptor = adaptor
        videoStartTimestamp = timestamp
    }

    private func writeConfidencePNG(_ confidenceMap: CVPixelBuffer, to url: URL) throws {
        let width = CVPixelBufferGetWidth(confidenceMap)
        let height = CVPixelBufferGetHeight(confidenceMap)
        let pixelFormat = CVPixelBufferGetPixelFormatType(confidenceMap)

        guard pixelFormat == kCVPixelFormatType_OneComponent8 else {
            throw NSError(domain: "DepthCaptureWriter", code: 10, userInfo: [NSLocalizedDescriptionKey: "Unsupported confidence format: \(pixelFormat)"])
        }

        CVPixelBufferLockBaseAddress(confidenceMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(confidenceMap, .readOnly) }

        guard let baseAddress = CVPixelBufferGetBaseAddress(confidenceMap) else {
            throw NSError(domain: "DepthCaptureWriter", code: 11, userInfo: [NSLocalizedDescriptionKey: "Confidence buffer has no base address"])
        }

        let bytesPerRow = CVPixelBufferGetBytesPerRow(confidenceMap)
        var rawData = Data(repeating: 0, count: width * height)
        rawData.withUnsafeMutableBytes { rawPtr in
            guard let destAddress = rawPtr.baseAddress else { return }
            for y in 0..<height {
                let srcRow = baseAddress.advanced(by: y * bytesPerRow)
                let destRow = destAddress.advanced(by: y * width)
                destRow.copyMemory(from: srcRow, byteCount: width)
            }
        }

        guard let provider = CGDataProvider(data: rawData as CFData) else {
            throw NSError(domain: "DepthCaptureWriter", code: 12, userInfo: [NSLocalizedDescriptionKey: "Failed to create CGDataProvider for confidence"])
        }

        let colorSpace = CGColorSpaceCreateDeviceGray()
        let bitmapInfo = CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue)

        guard let cgImage = CGImage(
            width: width,
            height: height,
            bitsPerComponent: 8,
            bitsPerPixel: 8,
            bytesPerRow: width,
            space: colorSpace,
            bitmapInfo: bitmapInfo,
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        ) else {
            throw NSError(domain: "DepthCaptureWriter", code: 13, userInfo: [NSLocalizedDescriptionKey: "Failed to create CGImage for confidence"])
        }

        guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else {
            throw NSError(domain: "DepthCaptureWriter", code: 14, userInfo: [NSLocalizedDescriptionKey: "Failed to create CGImageDestination for confidence PNG"])
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
            throw NSError(domain: "DepthCaptureWriter", code: 15, userInfo: [NSLocalizedDescriptionKey: "Failed to finalize confidence PNG"])
        }
    }

    private static func intrinsicsToArray(_ matrix: simd_float3x3) -> [Float] {
        return [
            matrix.columns.0.x, matrix.columns.0.y, matrix.columns.0.z,
            matrix.columns.1.x, matrix.columns.1.y, matrix.columns.1.z,
            matrix.columns.2.x, matrix.columns.2.y, matrix.columns.2.z
        ]
    }

    private static func transformToArray(_ matrix: simd_float4x4) -> [Float] {
        return [
            matrix.columns.0.x, matrix.columns.0.y, matrix.columns.0.z, matrix.columns.0.w,
            matrix.columns.1.x, matrix.columns.1.y, matrix.columns.1.z, matrix.columns.1.w,
            matrix.columns.2.x, matrix.columns.2.y, matrix.columns.2.z, matrix.columns.2.w,
            matrix.columns.3.x, matrix.columns.3.y, matrix.columns.3.z, matrix.columns.3.w
        ]
    }

    private static func pixelFormatName(_ value: OSType) -> String {
        switch value {
        case kCVPixelFormatType_DepthFloat32: return "DepthFloat32"
        case kCVPixelFormatType_DepthFloat16: return "DepthFloat16"
        case kCVPixelFormatType_OneComponent8: return "OneComponent8"
        default: return String(value)
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

    private static func convertDepthToFloat32(_ depthMap: CVPixelBuffer) throws -> [Float] {
        let width = CVPixelBufferGetWidth(depthMap)
        let height = CVPixelBufferGetHeight(depthMap)
        let pixelFormat = CVPixelBufferGetPixelFormatType(depthMap)

        CVPixelBufferLockBaseAddress(depthMap, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depthMap, .readOnly) }

        guard let baseAddress = CVPixelBufferGetBaseAddress(depthMap) else {
            throw NSError(domain: "DepthCaptureWriter", code: 16, userInfo: [NSLocalizedDescriptionKey: "Depth buffer has no base address"])
        }

        let rowBytes = CVPixelBufferGetBytesPerRow(depthMap)
        var out = [Float](repeating: .nan, count: width * height)
        switch pixelFormat {
        case kCVPixelFormatType_DepthFloat32:
            let floatPtr = baseAddress.assumingMemoryBound(to: Float.self)
            let stride = rowBytes / MemoryLayout<Float>.size
            for y in 0..<height {
                let rowOffset = y * stride
                let outOffset = y * width
                for x in 0..<width {
                    out[outOffset + x] = floatPtr[rowOffset + x]
                }
            }
        case kCVPixelFormatType_DepthFloat16:
            let halfPtr = baseAddress.assumingMemoryBound(to: UInt16.self)
            let stride = rowBytes / MemoryLayout<UInt16>.size
            for y in 0..<height {
                let rowOffset = y * stride
                let outOffset = y * width
                for x in 0..<width {
                    out[outOffset + x] = Float(Float16(bitPattern: halfPtr[rowOffset + x]))
                }
            }
        default:
            throw NSError(domain: "DepthCaptureWriter", code: 17, userInfo: [NSLocalizedDescriptionKey: "Unsupported raw depth pixel format: \(pixelFormat)"])
        }
        return out
    }

    private static func rawPixelBufferBytes(_ pixelBuffer: CVPixelBuffer) throws -> Data {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            throw NSError(domain: "DepthCaptureWriter", code: 18, userInfo: [NSLocalizedDescriptionKey: "Pixel buffer has no base address"])
        }
        return Data(bytes: baseAddress, count: CVPixelBufferGetBytesPerRow(pixelBuffer) * CVPixelBufferGetHeight(pixelBuffer))
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
final class DepthCaptureManager: NSObject, @preconcurrency ARSessionDelegate {
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

    func stopAndFinishRecording() async {
        isRecording = false
        await writer.setRecording(false)
        await writer.finishRecording()
        captureInFlight = false
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
        confidenceDirectory: URL?,
        streamsDirectory: URL? = nil,
        deltaThresholdMeanU16: Float,
        onSaved: (@Sendable (TimeInterval, String, String, String?, [Float]?, [Float]?) async -> Void)?,
        onV2Saved: (@Sendable (V2StreamFrameRecord) async -> Void)? = nil
    ) {
        let dd = depthDirectory
        let rd = rgbDirectory
        let cd = confidenceDirectory
        let sd = streamsDirectory
        let th = deltaThresholdMeanU16
        let cb = onSaved
        let v2 = onV2Saved
        Task {
            await writer.configure(
                depthDirectory: dd,
                rgbDirectory: rd,
                confidenceDirectory: cd,
                streamsDirectory: sd,
                deltaThresholdMeanU16: th,
                onSaved: cb,
                onV2Saved: v2
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
        let smoothedDepthMap = frame.smoothedSceneDepth.map { PixelBufferBox($0.depthMap) }
        let confidenceMap = depthData.confidenceMap.map { PixelBufferBox($0) }
        let capturedImage = PixelBufferBox(frame.capturedImage)
        let cameraIntrinsics = frame.camera.intrinsics
        let cameraTransform = frame.camera.transform

        Task {
            await writer.capture(
                timestamp: timestamp,
                depthMap: depthMap,
                smoothedDepthMap: smoothedDepthMap,
                confidenceMap: confidenceMap,
                capturedImage: capturedImage,
                cameraIntrinsics: cameraIntrinsics,
                cameraTransform: cameraTransform
            )
            self.captureInFlight = false
        }
    }
}
