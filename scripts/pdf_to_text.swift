// PDF 텍스트 추출 (macOS 내장 PDFKit). 설치할 것이 없다.
// 사용: swift scripts/pdf_to_text.swift <pdf 경로> [시작쪽 끝쪽]
// 출력: 쪽마다 "=====PAGE n=====" 줄 뒤에 그 쪽의 텍스트를 쓴다.
// 한계: 텍스트 레이어가 없는 스캔본은 빈 문자열이 나온다. 글자 사이 띄어쓰기가 PDF에 없으면 추출 결과에도 없다.
import Foundation
import PDFKit

let args = CommandLine.arguments
guard args.count >= 2, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("usage: swift scripts/pdf_to_text.swift <pdf> [firstPage lastPage]\n".data(using: .utf8)!)
    exit(1)
}
let first = args.count >= 4 ? max(1, Int(args[2]) ?? 1) : 1
let last = args.count >= 4 ? min(doc.pageCount, Int(args[3]) ?? doc.pageCount) : doc.pageCount
if first > last {
    FileHandle.standardError.write("page range is empty (pageCount=\(doc.pageCount))\n".data(using: .utf8)!)
    exit(1)
}
for n in first...last {
    print("=====PAGE \(n)=====")
    print(doc.page(at: n - 1)?.string ?? "")
}
