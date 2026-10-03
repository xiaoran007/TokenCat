import AppKit
import XCTest
@testable import TokenCat

@MainActor
final class TokenCatBrandTests: XCTestCase {
    func testBundledLogoResourcesLoadAndRemainVector() throws {
        for image in [TokenCatBrand.mark, TokenCatBrand.menuMark] {
            XCTAssertTrue(image.isValid)
            XCTAssertTrue(image.representations.contains { $0 is NSPDFImageRep })
            XCTAssertNotNil(image.cgImage(forProposedRect: nil, context: nil, hints: nil))
        }
    }

    func testMenuMarkUsesSystemTintAtMenuBarSize() {
        XCTAssertTrue(TokenCatBrand.menuMark.isTemplate)
        XCTAssertEqual(TokenCatBrand.menuMark.size, NSSize(width: 22, height: 18.5625))
    }
}
