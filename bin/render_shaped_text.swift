// Render transparent multilingual text with macOS CoreText shaping and fallback.
// Input: JSON array of {path,text,width,height,size,min_size?,rtl?,yellow?}.
import AppKit
import Foundation

let rows = try JSONSerialization.jsonObject(with: Data(contentsOf:
    URL(fileURLWithPath: CommandLine.arguments[1]))) as! [[String: Any]]
for row in rows {
    let width = row["width"] as! Int, height = row["height"] as! Int
    let text = row["text"] as! String
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width * 3,
        pixelsHigh: height * 3, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
        isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    let context = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSGraphicsContext.current = context
    context.cgContext.scaleBy(x: 3, y: 3)
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .center
    paragraph.lineBreakMode = .byWordWrapping
    paragraph.baseWritingDirection = row["rtl"] as? Bool == true ? .rightToLeft : .natural
    let minimum = CGFloat(row["min_size"] as? Double ?? 10)
    var size = CGFloat(row["size"] as! Double)
    var bounds = NSRect.zero
    var attrs: [NSAttributedString.Key: Any] = [:]
    while size >= minimum {
        attrs = [.font: NSFont.systemFont(ofSize: size, weight: .bold),
                 .paragraphStyle: paragraph, .foregroundColor: NSColor.white]
        bounds = (text as NSString).boundingRect(with:
            NSSize(width: width - 20, height: 10000),
            options: [.usesLineFragmentOrigin, .usesFontLeading], attributes: attrs)
        if bounds.height <= CGFloat(height - 14) { break }
        size -= 0.5
    }
    guard size >= minimum else { fatalError("Text does not fit: \(text)") }
    let rect = NSRect(x: 10, y: (CGFloat(height) - bounds.height) / 2,
                      width: CGFloat(width - 20), height: ceil(bounds.height) + 2)
    let yellow = row["yellow"] as? Bool == true
    attrs[.foregroundColor] = yellow ? NSColor(calibratedRed: 1, green: 0.91, blue: 0.18, alpha: 1) : NSColor.white
    if yellow {
        attrs[.strokeColor] = NSColor.white
        attrs[.strokeWidth] = -18
        (text as NSString).draw(with: rect, options: [.usesLineFragmentOrigin, .usesFontLeading], attributes: attrs)
    }
    attrs[.strokeColor] = NSColor.black
    attrs[.strokeWidth] = yellow ? -9 : -12
    (text as NSString).draw(with: rect, options: [.usesLineFragmentOrigin, .usesFontLeading], attributes: attrs)
    // Draw the fill last: a thick outline can otherwise cover narrow CJK strokes.
    attrs[.strokeWidth] = 0
    (text as NSString).draw(with: rect, options: [.usesLineFragmentOrigin, .usesFontLeading], attributes: attrs)
    NSGraphicsContext.restoreGraphicsState()
    let destination = URL(fileURLWithPath: row["path"] as! String)
    try bitmap.representation(using: .png, properties: [:])!.write(to: destination)
    print("\(destination.path) font=\(size)")
}
