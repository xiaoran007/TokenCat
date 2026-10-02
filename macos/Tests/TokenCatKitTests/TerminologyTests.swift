import XCTest
@testable import TokenCatKit

final class TerminologyTests: XCTestCase {
    private let chinese = Localizer(.simplifiedChinese)

    func testChineseUsageKeepsFamiliarTechnicalTerms() {
        let terms = [
            "tokens.title": "Tokens",
            "action.dashboard": "Dashboard",
            "cost.input": "Input",
            "cost.output": "Output",
            "cost.cacheRead": "Cache read",
            "cost.cacheWrite": "Cache write",
            "cost.reasoning": "Reasoning",
            "context.title": "Context",
            "usage.subtasks": "Subagents"
        ]
        for (key, term) in terms {
            XCTAssertTrue(chinese.text(key).contains(term), "\(key) should retain \(term)")
        }
        XCTAssertTrue(chinese.text("cost.reasoning").contains("包含在 Output 中"))
    }

    func testTechnicalTermsDoNotReplaceChinesePrivacyAndPricingExplanations() {
        let privacy = chinese.text("settings.privacyExplanation")
        XCTAssertTrue(privacy.contains("项目路径保留在本机"))
        XCTAssertTrue(privacy.contains("不会存储或展示提示词与响应正文、凭据或会话令牌"))

        let pricing = chinese.text("cost.explanation")
        XCTAssertTrue(pricing.contains("API 价格"))
        XCTAssertTrue(pricing.contains("不是订阅账单"))
        XCTAssertTrue(pricing.contains("不表示剩余额度"))
        XCTAssertTrue(chinese.text("tokens.reportedOnly").contains("缺失的元数据不会被当作零"))
    }
}
