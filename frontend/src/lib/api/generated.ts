// 생성 파일이다. 손으로 고치지 않는다.
// 원본: 백엔드 OpenAPI(MediAgent 0.1.0, backend/scripts/export_openapi.py 결과)
// 다시 만들기: pnpm gen:api
export interface paths {
    "/chat": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 질문을 받아 진행·응급·최종 응답 이벤트를 NDJSON으로 보낸다 */
        post: operations["chat_chat_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/consents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** 동의·철회 기록(철회는 즉시 삭제를 일으킨다) */
        post: operations["post_consents_consents_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description 서비스 상태 확인 엔드포인트. 200 OK를 반환한다.
         */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/legal/{doc_type}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * 약관·동의 문서 현재본(게스트 허용)
         * @description 토큰을 읽지 않는다(`/chat`처럼 게스트 경로). `version`을 주면 그 게시 버전.
         */
        get: operations["get_legal_legal__doc_type__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 로그인한 사용자 정보(첫 호출에 계정 행 생성, 온보딩·동의 상태) */
        get: operations["me_me_get"];
        put?: never;
        post?: never;
        /** 계정 삭제(프로필·복용 약·동의 기록 즉시 전부 파기) */
        delete: operations["delete_me_me_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/profiles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** 내 프로필 목록(본인 1 + 가족 최대 3) */
        get: operations["list_profiles_profiles_get"];
        put?: never;
        /** 프로필 추가 */
        post: operations["create_profile_profiles_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/profiles/{profile_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** 가족 프로필 삭제(본인 프로필은 409 SELF_REQUIRED) */
        delete: operations["delete_profile_profiles__profile_id__delete"];
        options?: never;
        head?: never;
        /** 프로필 수정(보낸 칸만, 약은 목록 전체 교체) */
        patch: operations["update_profile_profiles__profile_id__patch"];
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AgeInput
         * @description 먹는 사람의 나이 구간. 한 나이면 `lower == upper`.
         */
        AgeInput: {
            /** Lower */
            lower: number;
            /**
             * Unit
             * @default 세
             * @enum {string}
             */
            unit: "세" | "개월" | "주";
            /** Upper */
            upper: number;
        };
        /** AnswerEvent */
        AnswerEvent: {
            response: components["schemas"]["ChatResponse"];
            /**
             * Schema Version
             * @default chat_event@v1
             * @constant
             */
            schema_version: "chat_event@v1";
            /** Seq */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "answer";
        };
        /**
         * Badge
         * @description 판정 줄의 배지 하나(PRD-15-01·02). `text`는 AG-08 상수 문구, `source`는 등급 불일치일 때만(파일 → 성분 API).
         */
        Badge: {
            /** Evidence Id */
            evidence_id?: string | null;
            /** Grade */
            grade?: ("1" | "2" | "M") | null;
            /** Kind */
            kind: string;
            /** Note */
            note?: string | null;
            /** Source */
            source?: ("API_DIRECT" | "FILE" | "CORPUS_QUOTE") | null;
            /** Text */
            text: string;
        };
        /**
         * Candidate
         * @description 되묻기 후보 하나(BE-06-03 A, `end_reason == CLARIFY`일 때만). 이름만 보이고 먹어도 되는지는 말하지 않는다.
         */
        Candidate: {
            /** Entp Name */
            entp_name?: string | null;
            /** Input Name */
            input_name: string;
            /** Item Seq */
            item_seq?: string | null;
            /** Matched By */
            matched_by?: string | null;
            /** Name */
            name: string;
            /** Prescription */
            prescription?: string | null;
        };
        /**
         * ChatEvent
         * @description 스트림 이벤트 한 줄(판별 유니온, 키 `type`). OpenAPI에 `ChatEvent`로 노출된다.
         */
        ChatEvent: components["schemas"]["ProgressEvent"] | components["schemas"]["EmergencyEvent"] | components["schemas"]["AnswerEvent"] | components["schemas"]["ErrorEvent"] | components["schemas"]["DoneEvent"];
        /**
         * ChatRequest
         * @description `POST /chat` 본문.
         */
        ChatRequest: {
            context?: components["schemas"]["ConversationContext"];
            /** Question */
            question: string;
        };
        /**
         * ChatResponse
         * @description `/chat` 최종 응답(`chat_response@v1`). 스트림에서는 `answer` 이벤트의 `response`로 간다.
         */
        ChatResponse: {
            /** Candidates */
            candidates?: components["schemas"]["Candidate"][];
            /** Candidates Line */
            candidates_line?: string | null;
            /** Citations */
            citations?: components["schemas"]["Citation"][];
            /** Detail */
            detail?: components["schemas"]["DetailItem"][];
            /** Disclaimer */
            disclaimer: string;
            dose_check?: components["schemas"]["DoseCheck"] | null;
            /** Dose Notice */
            dose_notice?: string | null;
            emergency?: components["schemas"]["Emergency"] | null;
            /** End Reason */
            end_reason?: ("NORMAL" | "CLARIFY" | "REFUSE" | "LIMIT" | "VALIDATION_FALLBACK") | null;
            /** Findings */
            findings?: components["schemas"]["Finding"][];
            /** Fixed Notice */
            fixed_notice: string[];
            /** Grade Def Missing */
            grade_def_missing?: string[];
            /** Grade Defs */
            grade_defs?: components["schemas"]["GradeDef"][];
            /** Name Corrections */
            name_corrections?: components["schemas"]["NameCorrection"][];
            /** Not Checked Lines */
            not_checked_lines?: string[];
            /** Notice */
            notice?: string | null;
            /** Pharmacist Advice */
            pharmacist_advice?: string[];
            /** Pharmacist Advice Kinds */
            pharmacist_advice_kinds?: ("missing" | "grade_def")[];
            /** Redose Notice */
            redose_notice?: string | null;
            rest_fold?: components["schemas"]["RestFold"] | null;
            result_summary?: components["schemas"]["ResultSummary"] | null;
            /**
             * Route
             * @enum {string}
             */
            route: "AGENT" | "REFUSE";
            /**
             * Schema Version
             * @default chat_response@v1
             * @constant
             */
            schema_version: "chat_response@v1";
            /** Sentence Refs */
            sentence_refs?: components["schemas"]["SentenceRef"][];
            /** Summary */
            summary: string | null;
        };
        /**
         * Citation
         * @description 출처 표 한 행(PRD-11-02·PRD-12 §6). `publisher`는 공식 기관 이름만(서비스 이름 금지, PRD-14). 고시 번호·판·쪽은 이 행에 둔다(BE-06-05 A).
         */
        Citation: {
            /** Dataset */
            dataset: string;
            /** Dates */
            dates: components["schemas"]["DateLine"][];
            /** Edition */
            edition?: string | null;
            /** Evidence Ids */
            evidence_ids?: string[];
            /** Notice Nos */
            notice_nos?: string[];
            /** Pages */
            pages?: string[];
            /** Publisher */
            publisher: string;
            /** Source Kind */
            source_kind?: ("API_DIRECT" | "FILE" | "CORPUS_QUOTE") | null;
        };
        /**
         * ConfirmedDrug
         * @description 되묻기 등으로 사용자가 고른 약(이름과, 있으면 품목기준코드).
         *
         *     `input_name`(선택, FE-09-05 A)은 그 약을 고른 되묻기 묶음의 이름(응답 `candidates[].input_name` 그대로)이다. 있으면 서버가 질문 속 그 이름의
         *     약에만 이 코드를 확정한다(묶음 후보가 겹쳐도 다른 묶음을 덮지 않는다). 없으면 이전 규칙(후보 집합 포함 + 나중 것) 그대로다.
         */
        ConfirmedDrug: {
            /** Input Name */
            input_name?: string | null;
            /** Item Seq */
            item_seq?: string | null;
            /** Name */
            name: string;
        };
        /** ConsentItem */
        ConsentItem: {
            /**
             * Action
             * @enum {string}
             */
            action: "agree" | "withdraw";
            /**
             * Doc Type
             * @enum {string}
             */
            doc_type: "terms" | "privacy_consent" | "sensitive_consent";
            /** Version */
            version: number;
        };
        /** ConsentRequest */
        ConsentRequest: {
            /**
             * Channel
             * @enum {string}
             */
            channel: "onboarding" | "settings" | "reconsent";
            /** Items */
            items: components["schemas"]["ConsentItem"][];
        };
        /** ConsentState */
        ConsentState: {
            /** Acted At */
            acted_at: string | null;
            /** Agreed Version */
            agreed_version: number | null;
            /** Current Version */
            current_version: number;
            /**
             * Doc Type
             * @enum {string}
             */
            doc_type: "terms" | "privacy_consent" | "sensitive_consent";
            /** Needs Consent */
            needs_consent: boolean;
            /** Needs Reconsent */
            needs_reconsent: boolean;
            /** Required */
            required: boolean;
        };
        /**
         * ConversationContext
         * @description 같은 대화 안에서 이미 말한 값(한 입력 묶음, PRD-07-01 A). 서버는 저장·로그하지 않는다.
         *
         *     - `confirmed_drugs`: **이번 질문의 되묻기 답**(같은 질문을 다시 보낼 때만 채운다, AG-21-02 A로 의미 축소). 서버가 바로 확정한다.
         *     - `prior_drugs`(AG-21-02 A): **이전 차례에서 고른 약**(모양은 `confirmed_drugs`와 같다). 확정에 쓰지 않고, 같은 이름이 다시 나오면
         *       그 약을 첫 후보로 둔 확인 되묻기에만 쓴다. 이벤트·로그에는 개수만 남는다.
         *     - `took_today`(AG-22-05 A): 용량주의 되묻기 답(예 `true` / 아니요 `false`, 답하지 않았으면 없음). 시각·양은 받지 않는다(RFP-21-03).
         *       저장·로그·이벤트에 남기지 않는다.
         */
        ConversationContext: {
            age?: components["schemas"]["AgeInput"] | null;
            /** Confirmed Drugs */
            confirmed_drugs?: components["schemas"]["ConfirmedDrug"][];
            /** Pregnant */
            pregnant?: boolean | null;
            /** Prior Drugs */
            prior_drugs?: components["schemas"]["ConfirmedDrug"][];
            /** Took Today */
            took_today?: boolean | null;
        };
        /**
         * DateLine
         * @description 날짜 한 줄(한 날짜 = 한 항목). `날짜 없음`만 `value`가 None이다. 값은 `YYYY-MM-DD` 또는 `YYYY-MM`(조회 제외).
         */
        DateLine: {
            /** Label */
            label: string;
            /** Value */
            value: string | null;
        };
        /**
         * DetailItem
         * @description 근거 상세 한 박스(AG-06 `renderer` 결과에 자료 약칭·기관·날짜 줄을 더한 것). LLM 문장 없음.
         *
         *     원문 인용(허가사항 용법용량 포함)은 `rows[]`의 원문 텍스트 칸 그대로이며 표 구조(`dose_table` 등)는 두지 않는다(BE-06-04 B).
         */
        DetailItem: {
            /** Dataset */
            dataset: string | null;
            /** Dataset Key */
            dataset_key: string | null;
            /** Dates */
            dates: components["schemas"]["DateLine"][];
            /** Drug Name */
            drug_name?: string | null;
            /** Drugs */
            drugs?: string[] | null;
            /** Easy Text Missing Line */
            easy_text_missing_line?: string | null;
            /** Evidence Id */
            evidence_id: string | null;
            /** Flags */
            flags?: string[];
            /** Item Seq */
            item_seq?: string | null;
            /** Kind */
            kind: string | null;
            /** Label Help */
            label_help?: string | null;
            /** Label Source */
            label_source?: string | null;
            /** Missing Reason */
            missing_reason?: string | null;
            /** Missing Text */
            missing_text?: string | null;
            /** Notes */
            notes?: string[];
            /** Publisher */
            publisher: string | null;
            /** Quote Notice */
            quote_notice?: string | null;
            /** Rows */
            rows?: {
                [key: string]: unknown;
            }[];
            /** Section */
            section?: string | null;
            /** Source Kind */
            source_kind: ("API_DIRECT" | "FILE" | "CORPUS_QUOTE") | null;
            /** Source Kind Label */
            source_kind_label?: string | null;
            /** Status */
            status: string | null;
        };
        /** DoneEvent */
        DoneEvent: {
            /** End Reason */
            end_reason?: ("NORMAL" | "CLARIFY" | "REFUSE" | "LIMIT" | "VALIDATION_FALLBACK") | null;
            /**
             * Schema Version
             * @default chat_event@v1
             * @constant
             */
            schema_version: "chat_event@v1";
            /** Seq */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "done";
        };
        /**
         * DoseCheck
         * @description 용량주의 되묻기(AG-22-02 B·05 A): 용량주의 성분 FOUND ∧ 복용 관련 질문 ∧ 아직 답 없음일 때 결과와 함께 온다.
         *
         *     화면은 `options` 중 하나를 고르면 같은 질문을 `context.took_today`(예 → true, 아니요 → false)와 함께 다시 보낸다. 시각·양은 묻지 않는다.
         */
        DoseCheck: {
            /** Drugs */
            drugs?: string[];
            /** Evidence Ids */
            evidence_ids?: string[];
            /** Options */
            options: string[];
            /** Question */
            question: string;
        };
        /**
         * Emergency
         * @description 119 안내(BE-06-02 A: `end_reason`과 별개 신호). 문구·전화 링크는 상수 그대로다.
         */
        Emergency: {
            /** Tel */
            tel: string;
            /** Text */
            text: string;
            /**
             * Wide Text
             * @default 컴퓨터로 보고 있다면 휴대폰으로 119에 전화하세요.
             */
            wide_text: string;
        };
        /** EmergencyEvent */
        EmergencyEvent: {
            emergency: components["schemas"]["Emergency"];
            /**
             * Schema Version
             * @default chat_event@v1
             * @constant
             */
            schema_version: "chat_event@v1";
            /** Seq */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "emergency";
        };
        /**
         * ErrorBody
         * @description 4xx·5xx JSON 본문. 입력 값·내부 정보는 싣지 않는다.
         */
        ErrorBody: {
            /** Code */
            code: string;
            /**
             * Fields
             * @default []
             */
            fields: string[];
        };
        /** ErrorEvent */
        ErrorEvent: {
            /**
             * Code
             * @enum {string}
             */
            code: "INTERNAL_ERROR" | "TIMEOUT" | "UPSTREAM_UNAVAILABLE";
            /** Message */
            message?: string | null;
            /**
             * Schema Version
             * @default chat_event@v1
             * @constant
             */
            schema_version: "chat_event@v1";
            /** Seq */
            seq: number;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "error";
        };
        /**
         * Finding
         * @description 판정 줄(`finalize.entries` 한 항목). 제품 줄 또는 쌍 줄(BE-06-01 A). 문구는 코드 상수.
         */
        Finding: {
            /** Age Criteria */
            age_criteria?: string[];
            /** Age Info Line */
            age_info_line?: string | null;
            /** Badges */
            badges?: components["schemas"]["Badge"][];
            /**
             * Bucket
             * @enum {string}
             */
            bucket: "found" | "not_listed" | "identified" | "unconfirmed";
            /** Caution Desc */
            caution_desc?: string | null;
            /** Drug */
            drug: string;
            /** Drugs */
            drugs?: string[];
            /** Evidence Id */
            evidence_id: string | null;
            /** Grades */
            grades?: string[];
            /** Ingredients */
            ingredients?: components["schemas"]["Ingredient"][];
            /** Input Name */
            input_name?: string | null;
            /** Kind */
            kind: string | null;
            /** Next */
            next?: string | null;
            /** Note */
            note?: string | null;
            /** Notes */
            notes?: string[];
            /** Notice Nos */
            notice_nos?: string[];
            pair_ref?: components["schemas"]["PairRef"] | null;
            /** Reasons */
            reasons?: string[];
            /** Reference Line */
            reference_line?: string | null;
            /** Retried */
            retried?: boolean | null;
            /** Retried Line */
            retried_line?: string | null;
            /** Searched */
            searched?: components["schemas"]["Searched"][];
            /** Section */
            section?: ("core" | "caution" | "rest" | "unconfirmed") | null;
            /** Source Label */
            source_label?: string | null;
            /** Sub Line */
            sub_line?: string | null;
            /**
             * Target
             * @default product
             * @enum {string}
             */
            target: "product" | "pair";
            /** Text */
            text: string;
            /**
             * Unresolved
             * @default false
             */
            unresolved: boolean;
            /** Why */
            why?: string | null;
        };
        /**
         * GradeDef
         * @description 등급 정의 블록 하나(BE-06-16 A, PRD-09-04·PRD-15-03). 원문(`text`)과 미확보 사유는 둘 중 하나만 있다.
         *
         *     제목·미확보 문구는 상수이고 원문·출처 줄은 코드가 청크에서 읽은 글자 그대로다. 원문이 없으면 출처 줄도 없다.
         */
        GradeDef: {
            /**
             * Grade
             * @enum {string}
             */
            grade: "1" | "2" | "M";
            /** Missing Reason */
            missing_reason?: ("FETCH_FAIL" | "OUT_OF_SCOPE") | null;
            /** Missing Text */
            missing_text?: string | null;
            /** Source */
            source?: string | null;
            /** Text */
            text?: string | null;
            /** Title */
            title: string;
        };
        /**
         * Ingredient
         * @description 제품 줄의 성분 하나(PRD-09-05). 성분명으로만 식별한 약은 그 성분 하나만 담는다.
         */
        Ingredient: {
            /** Code */
            code?: string | null;
            /** Code Missing Text */
            code_missing_text?: string | null;
            /** Contra Kinds */
            contra_kinds?: string[] | null;
            /** Dup */
            dup?: boolean | null;
            /** Name */
            name: string;
            /** State Labels */
            state_labels?: string[];
        };
        /**
         * LegalDocumentOut
         * @description `GET /legal/{doc_type}`. `legal_review="not_reviewed"`이면 프런트가 "초안·법률 검토 전" 표지를 그린다.
         */
        LegalDocumentOut: {
            /** Body Md */
            body_md: string;
            /** Body Sha256 */
            body_sha256: string;
            /**
             * Doc Type
             * @enum {string}
             */
            doc_type: "terms" | "privacy_policy" | "privacy_consent" | "sensitive_consent";
            /**
             * Effective At
             * Format: date-time
             */
            effective_at: string;
            /**
             * Legal Review
             * @enum {string}
             */
            legal_review: "not_reviewed" | "reviewed";
            /** Required */
            required: boolean;
            /** Requires Reconsent */
            requires_reconsent: boolean;
            /** Title */
            title: string;
            /** Version */
            version: number;
        };
        /**
         * MeResponse
         * @description `GET /me`·`POST /consents` 응답. 이메일 등 로그인 정보는 싣지 않는다(설계 9.3절).
         */
        MeResponse: {
            /** Consents */
            consents: components["schemas"]["ConsentState"][];
            /** Health Consent Active */
            health_consent_active: boolean;
            /**
             * Is Guest
             * @default false
             */
            is_guest: boolean;
            /** Onboarding Completed At */
            onboarding_completed_at: string | null;
            /**
             * Onboarding Step
             * @enum {string}
             */
            onboarding_step: "consent" | "profile_self" | "family" | "done";
            /**
             * Profile Limit
             * @default 4
             */
            profile_limit: number;
            /** User Id */
            user_id: string;
        };
        /** MedicationIn */
        MedicationIn: {
            /** Input Text */
            input_text: string;
            /** Item Seq */
            item_seq?: string | null;
        };
        /** MedicationOut */
        MedicationOut: {
            /** Confirmed At */
            confirmed_at: string | null;
            /** Input Text */
            input_text: string;
            /** Item Seq */
            item_seq: string | null;
            /** Medication Id */
            medication_id: string;
        };
        /**
         * NameCorrection
         * @description 오탈자 보정 고지 한 줄(AG-10-02 A). 질문에 적힌 이름 조각(`input`)을 비슷한 사전 이름(`name`) 하나로 보고 확인했다는 표시다.
         *
         *     `text`는 상수 `TYPO_CORRECTED_LINE`에 두 이름을 넣은 문장 그대로다(화면은 문장을 조립하지 않는다). 판정이 아니다.
         */
        NameCorrection: {
            /** Input */
            input: string;
            /** Name */
            name: string;
            /** Text */
            text: string;
        };
        /**
         * PairFound
         * @description 요약에 든 걸린 짝 하나: 두 약 표시 이름과 그 짝 줄의 근거 ID.
         */
        PairFound: {
            /** Drugs */
            drugs: string[];
            /** Evidence Ids */
            evidence_ids?: string[];
        };
        /**
         * PairRef
         * @description 제품 줄의 병용금기 짝 참조(FE-11-05 A, AG-08-29 A 대체). 제품 줄에는 "삐! 병용금기" 배지를 달지 않고 이 보조줄만 둔다.
         *
         *     `evidence_ids`는 그 약이 낀 병용금기 FOUND 짝 줄의 근거 ID(짝 줄 `evidence_id`와 같은 값), `text`는 상수 `PAIR_REF_LINE` 그대로.
         */
        PairRef: {
            /** Count */
            count: number;
            /** Evidence Ids */
            evidence_ids: string[];
            /** Text */
            text: string;
        };
        /** ProfileCreate */
        ProfileCreate: {
            /** Age Band */
            age_band?: ("m0_2" | "m3_5" | "m6_11" | "y1" | "y2" | "y3_5" | "y6_11" | "y12_14" | "y15_18" | "y19_64" | "y65_plus") | null;
            /** Label */
            label?: string | null;
            /** Medications */
            medications?: components["schemas"]["MedicationIn"][];
            /** Pregnancy Status */
            pregnancy_status?: ("pregnant" | "not_pregnant" | "unknown") | null;
            /**
             * Relation
             * @enum {string}
             */
            relation: "self" | "child" | "parent" | "spouse" | "other";
        };
        /** ProfileOut */
        ProfileOut: {
            /** Age Band */
            age_band: ("m0_2" | "m3_5" | "m6_11" | "y1" | "y2" | "y3_5" | "y6_11" | "y12_14" | "y15_18" | "y19_64" | "y65_plus") | null;
            /** Label */
            label: string | null;
            /** Medications */
            medications: components["schemas"]["MedicationOut"][];
            /** Pregnancy Status */
            pregnancy_status: ("pregnant" | "not_pregnant" | "unknown") | null;
            /** Profile Id */
            profile_id: string;
            /**
             * Relation
             * @enum {string}
             */
            relation: "self" | "child" | "parent" | "spouse" | "other";
            /** Sort Order */
            sort_order: number;
        };
        /**
         * ProfileUpdate
         * @description 보낸 칸만 바꾼다. `null`은 지움. `medications`를 보내면 목록 전체 교체.
         */
        ProfileUpdate: {
            /** Age Band */
            age_band?: ("m0_2" | "m3_5" | "m6_11" | "y1" | "y2" | "y3_5" | "y6_11" | "y12_14" | "y15_18" | "y19_64" | "y65_plus") | null;
            /** Label */
            label?: string | null;
            /** Medications */
            medications?: components["schemas"]["MedicationIn"][] | null;
            /** Pregnancy Status */
            pregnancy_status?: ("pregnant" | "not_pregnant" | "unknown") | null;
            /** Relation */
            relation?: ("self" | "child" | "parent" | "spouse" | "other") | null;
        };
        /** ProgressEvent */
        ProgressEvent: {
            /** Label */
            label: string;
            /**
             * Schema Version
             * @default chat_event@v1
             * @constant
             */
            schema_version: "chat_event@v1";
            /** Seq */
            seq: number;
            /**
             * Stage
             * @enum {string}
             */
            stage: "drug_lookup" | "contraindication_check" | "evidence_search";
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "progress";
        };
        /** Quote */
        Quote: {
            /** End */
            end: number;
            /** Start */
            start: number;
            /** Text */
            text: string;
        };
        /**
         * RestFold
         * @description 나머지 구역 접힘 줄(문구 ⑥, AG-22-07 A). `count`는 `section == "rest"`인 판정 줄 수이고 응답이 스스로 센다(화면은 세지 않는다).
         */
        RestFold: {
            /**
             * Close Label
             * @default 접기
             */
            close_label: string;
            /** Count */
            count: number;
            /**
             * Open Label
             * @default 펼치기
             */
            open_label: string;
            /** Text */
            text: string;
        };
        /**
         * ResultSummary
         * @description 약 2개 이상 결과의 맨 위 요약(FE-11-04 A, 문구 ④⑤). LLM `summary`와 별개의 코드 칸이다. 화면은 `text`·`pair_only_notice`를 그대로 그린다.
         *
         *     `text`는 상수 틀에 수치·짝을 넣은 글자 그대로, `pair_only_notice`는 약 3개 이상일 때만 상수 `PAIR_ONLY_NOTICE`(FE-11-06 A).
         */
        ResultSummary: {
            /** N Drugs */
            n_drugs: number;
            /** N Pairs */
            n_pairs: number;
            /** N Pairs Unchecked */
            n_pairs_unchecked: number;
            /** Pair Only Notice */
            pair_only_notice?: string | null;
            /** Pairs Found */
            pairs_found?: components["schemas"]["PairFound"][];
            /** Text */
            text: string;
        };
        /** Searched */
        Searched: {
            /** Count */
            count?: number | null;
            /** Dataset */
            dataset: string | null;
        };
        /**
         * SentenceRef
         * @description 요약 문장이 인용한 근거(문장 번호 ↔ 근거 ID, 코드가 원문에서 자른 인용).
         */
        SentenceRef: {
            /** Evidence Id */
            evidence_id: string;
            /** Quotes */
            quotes?: components["schemas"]["Quote"][];
            /** Row Key */
            row_key?: string | null;
            /** Sentence Index */
            sentence_index: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    chat_chat_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChatRequest"];
            };
        };
        responses: {
            /** @description NDJSON 스트림. 줄마다 ChatEvent 하나(순서 규칙은 app.api.events). */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/x-ndjson": components["schemas"]["ChatEvent"];
                };
            };
            /** @description 요청 형식 오류(빈 질문·길이 초과·모르는 칸). 입력 값은 되돌려 주지 않는다. */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 그래프 연결 전(의도된 상태). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    post_consents_consents_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConsentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MeResponse"];
                };
            };
            /** @description AUTH_REQUIRED·AUTH_INVALID(계정 행 없음 포함). */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description CONSENT_REQUIRED·RECONSENT_REQUIRED(fields=문서 종류). */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 현재본 없는 문서. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description VERSION_MISMATCH·USE_ACCOUNT_DELETE(fields=문서 종류). */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description INVALID_REQUEST 등 형식·상한·건강 정보 동의 오류. 입력 값은 되돌려 주지 않는다. */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 토큰 검증기 또는 계정 저장소 미설정(의도된 상태). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description AUTH_UNAVAILABLE(검증 서버) 또는 ACCOUNT_UNAVAILABLE(저장소). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    get_legal_legal__doc_type__get: {
        parameters: {
            query?: {
                version?: number | null;
            };
            header?: never;
            path: {
                doc_type: "terms" | "privacy_policy" | "privacy_consent" | "sensitive_consent";
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LegalDocumentOut"];
                };
            };
            /** @description 게시된 문서 없음. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description INVALID_REQUEST 등 형식·상한·건강 정보 동의 오류. 입력 값은 되돌려 주지 않는다. */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 토큰 검증기 또는 계정 저장소 미설정(의도된 상태). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description AUTH_UNAVAILABLE(검증 서버) 또는 ACCOUNT_UNAVAILABLE(저장소). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    me_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MeResponse"];
                };
            };
            /** @description AUTH_REQUIRED·AUTH_INVALID(계정 행 없음 포함). */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 토큰 검증기 또는 계정 저장소 미설정(의도된 상태). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description AUTH_UNAVAILABLE(검증 서버) 또는 ACCOUNT_UNAVAILABLE(저장소). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    delete_me_me_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description AUTH_REQUIRED·AUTH_INVALID(계정 행 없음 포함). */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 토큰 검증기 또는 계정 저장소 미설정(의도된 상태). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description AUTH_UNAVAILABLE(검증 서버) 또는 ACCOUNT_UNAVAILABLE(저장소). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    list_profiles_profiles_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProfileOut"][];
                };
            };
            /** @description AUTH_REQUIRED·AUTH_INVALID(계정 행 없음 포함). */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description CONSENT_REQUIRED·RECONSENT_REQUIRED(fields=문서 종류). */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description INVALID_REQUEST 등 형식·상한·건강 정보 동의 오류. 입력 값은 되돌려 주지 않는다. */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 토큰 검증기 또는 계정 저장소 미설정(의도된 상태). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description AUTH_UNAVAILABLE(검증 서버) 또는 ACCOUNT_UNAVAILABLE(저장소). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    create_profile_profiles_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProfileCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProfileOut"];
                };
            };
            /** @description AUTH_REQUIRED·AUTH_INVALID(계정 행 없음 포함). */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description CONSENT_REQUIRED·RECONSENT_REQUIRED(fields=문서 종류). */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description SELF_EXISTS(본인 프로필은 1개). */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description INVALID_REQUEST 등 형식·상한·건강 정보 동의 오류. 입력 값은 되돌려 주지 않는다. */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 토큰 검증기 또는 계정 저장소 미설정(의도된 상태). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description AUTH_UNAVAILABLE(검증 서버) 또는 ACCOUNT_UNAVAILABLE(저장소). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    delete_profile_profiles__profile_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                profile_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description AUTH_REQUIRED·AUTH_INVALID(계정 행 없음 포함). */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description CONSENT_REQUIRED·RECONSENT_REQUIRED(fields=문서 종류). */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 없는 프로필(남의 것 포함). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description SELF_REQUIRED. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description INVALID_REQUEST 등 형식·상한·건강 정보 동의 오류. 입력 값은 되돌려 주지 않는다. */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 토큰 검증기 또는 계정 저장소 미설정(의도된 상태). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description AUTH_UNAVAILABLE(검증 서버) 또는 ACCOUNT_UNAVAILABLE(저장소). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
    update_profile_profiles__profile_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                profile_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProfileUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProfileOut"];
                };
            };
            /** @description AUTH_REQUIRED·AUTH_INVALID(계정 행 없음 포함). */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description CONSENT_REQUIRED·RECONSENT_REQUIRED(fields=문서 종류). */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 없는 프로필(남의 것 포함). */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description SELF_EXISTS·SELF_FIXED(본인 관계는 바꾸지 않는다). */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description INVALID_REQUEST 등 형식·상한·건강 정보 동의 오류. 입력 값은 되돌려 주지 않는다. */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description 토큰 검증기 또는 계정 저장소 미설정(의도된 상태). */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
            /** @description AUTH_UNAVAILABLE(검증 서버) 또는 ACCOUNT_UNAVAILABLE(저장소). */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorBody"];
                };
            };
        };
    };
}
