import UIKit

/// Delegate that receives live and committed stroke paths in the
/// canvas's coordinate system.
protocol PumicePencilGestureDelegate: AnyObject {
    func pencilGestureDidUpdate(path: UIBezierPath, samples: [PencilStrokeSample])
    func pencilGestureDidFinish(path: UIBezierPath, samples: [PencilStrokeSample])
}

/// Custom drawing gesture recognizer that fires only for Apple Pencil
/// touches. Finger touches (`.direct`) and indirect inputs are
/// rejected so they fall through to PDFView's scroll gesture.
///
/// PencilKit's `PKCanvasView` with `drawingPolicy = .pencilOnly` was
/// supposed to do this for us, but on iPadOS 26 inside PDFKit's
/// per-page overlay it never activates — the pen falls through to
/// PDFView's scroll regardless of how the canvas is set up. Multiple
/// iterations (markup mode, becomeFirstResponder timing, tool-picker
/// observation, PDFPageView userInteractionEnabled) didn't help.
/// Going back to plain UIGestureRecognizer subclass gives us
/// deterministic control over which touches start a stroke.
final class PumicePencilGestureRecognizer: UIGestureRecognizer {
    weak var pencilDelegate: PumicePencilGestureDelegate?
    private var currentPath: UIBezierPath?
    private var samples: [PencilStrokeSample] = []
    private var strokeStartTimestamp: TimeInterval = 0

    override init(target: Any?, action: Selector?) {
        super.init(target: target, action: action)
        // Explicitly tell iOS this gesture only fires for pencil
        // touches. Without this, the gesture competes against PDFView's
        // pan gesture for finger touches too and may lose priority.
        allowedTouchTypes = [NSNumber(value: UITouch.TouchType.pencil.rawValue)]
    }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent) {
        super.touchesBegan(touches, with: event)
        guard let touch = touches.first,
              touch.type == .pencil
        else {
            state = .failed
            return
        }
        // `allowedTouchTypes` filters this recognizer to Pencil touches.
        // Do not also reject based on `event.allTouches`: UIKit can expose
        // a concurrent direct finger/palm touch there, which must remain
        // available to PDFView without cancelling the Pencil stroke.
        let path = UIBezierPath()
        path.lineJoinStyle = .round
        path.lineCapStyle = .round
        path.move(to: touch.location(in: view))
        currentPath = path
        strokeStartTimestamp = touch.timestamp
        samples = [sample(for: touch)]
        state = .began
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent) {
        super.touchesMoved(touches, with: event)
        guard let path = currentPath,
              let touch = touches.first,
              touch.type == .pencil
        else { return }
        // Use UIEvent.coalescedTouches to pull every sub-touch event
        // the system collected since the last call. Apple Pencil 2/Pro
        // emits up to ~240Hz of touch samples, but UIKit batches them
        // into one touchesMoved call per refresh — without coalescing
        // we'd drop most of them and the resulting path is jagged at
        // anything above a slow pen speed.
        for sub in event.coalescedTouches(for: touch) ?? [touch] {
            path.addLine(to: sub.location(in: view))
            samples.append(sample(for: sub))
        }
        pencilDelegate?.pencilGestureDidUpdate(path: path, samples: samples)
        state = .changed
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent) {
        super.touchesEnded(touches, with: event)
        guard let path = currentPath,
              let touch = touches.first,
              touch.type == .pencil
        else {
            state = .ended
            return
        }
        for sub in event.coalescedTouches(for: touch) ?? [touch] {
            path.addLine(to: sub.location(in: view))
            samples.append(sample(for: sub))
        }
        pencilDelegate?.pencilGestureDidFinish(path: path, samples: samples)
        currentPath = nil
        samples.removeAll()
        state = .ended
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent) {
        super.touchesCancelled(touches, with: event)
        currentPath = nil
        samples.removeAll()
        state = .cancelled
    }

    private func sample(for touch: UITouch) -> PencilStrokeSample {
        let maximum = touch.maximumPossibleForce
        let pressure = maximum > 0 ? min(1, max(0, touch.force / maximum)) : 0.5
        let elapsed = max(0, touch.timestamp - strokeStartTimestamp)
        return PencilStrokeSample(
            location: touch.location(in: view),
            pressure: pressure,
            timeMilliseconds: Int((elapsed * 1000).rounded())
        )
    }
}
