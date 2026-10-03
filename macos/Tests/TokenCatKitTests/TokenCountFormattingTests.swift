import XCTest
@testable import TokenCatKit

final class TokenCountFormattingTests: XCTestCase {
    func testTokenAbbreviationsStayConsistentAcrossLanguages() {
        let examples: [(UInt64, String)] = [
            (0, "0"), (999, "999"), (1_000, "1K"), (12_345, "12.35K"),
            (999_999, "1M"), (1_000_000, "1M"), (88_199_529, "88.2M"),
            (1_250_000_000, "1.25B"), (2_500_000_000_000, "2.5T")
        ]
        for language in [AppLanguage.english, .simplifiedChinese] {
            let strings = Localizer(language)
            for (tokens, expected) in examples {
                XCTAssertEqual(strings.compactCount(tokens), expected, "\(language): \(tokens)")
            }
        }
    }

    func testExactTokenCountsRemainUnrounded() {
        for language in [AppLanguage.english, .simplifiedChinese] {
            let strings = Localizer(language)
            XCTAssertEqual(strings.count(88_199_529), "88,199,529")
            XCTAssertEqual(strings.count(UInt64.max), "18,446,744,073,709,551,615")
        }
    }
}
