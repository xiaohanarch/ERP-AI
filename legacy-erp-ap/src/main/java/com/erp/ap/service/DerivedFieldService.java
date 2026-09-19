package com.erp.ap.service;

import com.erp.ap.boapi.BoApiException;
import com.erp.ap.domain.Invoice;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 本体驱动的派生字段求值引擎（通用，零字段特定逻辑）。
 *
 * 派生字段定义由构建期生成器从语义层增量段产出（derived-fields.json，
 * 携带语义版本戳）；本服务只做声明式求值：compute { op, left, right }，
 * 基字段按 snake_case -&gt; camelCase 反射读取实体——本体改定义、重建，
 * API 能力随之改变（ap.invoice.getDerivedField）。
 */
@Service
@RequiredArgsConstructor
public class DerivedFieldService {

    private final ValidationService validationService;
    private final ObjectMapper objectMapper;

    private JsonNode definitions;   // derived-fields.json（生成物，构建期从本体生成）
    private String ontologyVersion;

    @PostConstruct
    void load() throws Exception {
        try (var in = new ClassPathResource("derived-fields.json").getInputStream()) {
            definitions = objectMapper.readTree(in);
            ontologyVersion = definitions.path("semanticVersion").asText("unknown");
        }
    }

    public Map<String, Object> evaluate(String invoiceNo, String fieldName) {
        Invoice invoice = validationService.loadInvoiceInScope(invoiceNo);
        JsonNode def = null;
        for (JsonNode f : definitions.path("derivedFields")) {
            if (fieldName.equals(f.path("name").asText())) {
                def = f;
                break;
            }
        }
        if (def == null) {
            throw BoApiException.notFound("AP.DERIVED_FIELD_NOT_FOUND",
                    "派生字段 " + fieldName + " 未在本体增量段定义（可用：" + availableNames() + "）");
        }
        JsonNode compute = def.path("compute");
        String leftName = compute.path("left").asText();
        String rightName = compute.path("right").asText();
        BigDecimal left = readBase(invoice, leftName);
        BigDecimal right = readBase(invoice, rightName);
        BigDecimal value = switch (compute.path("op").asText()) {
            case "subtract" -> left.subtract(right);
            case "add" -> left.add(right);
            default -> throw BoApiException.validation("AP.VALIDATION_ERROR",
                    "不支持的计算式：" + compute.path("op").asText());
        };

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("invoiceNo", invoice.getInvoiceNo());
        out.put("field", fieldName);
        out.put("entity", def.path("entity").asText());
        out.put("value", value);
        out.put("unit", def.path("unit").asText(null));
        out.put("description", def.path("description").asText(null));
        out.put("formula", def.path("formula").asText());
        out.put("baseFields", List.of(leftName, rightName));
        out.put("baseValues", Map.of(leftName, left, rightName, right));
        out.put("ontologyVersion", ontologyVersion);
        out.put("drivenBy", "ontology increment.derived_fields（构建期生成 derived-fields.json）");
        return out;
    }

    /** 基字段按本体声明的 snake_case 名读取实体（反射 + 驼峰转换）。 */
    private BigDecimal readBase(Invoice invoice, String snake) {
        try {
            Field f = Invoice.class.getDeclaredField(snakeToCamel(snake));
            f.setAccessible(true);
            Object v = f.get(invoice);
            if (v instanceof BigDecimal d) {
                return d;
            }
            if (v instanceof Number n) {
                return new BigDecimal(n.toString());
            }
            throw BoApiException.validation("AP.VALIDATION_ERROR",
                    "基字段 " + snake + " 不是数值型，无法参与计算");
        } catch (NoSuchFieldException | IllegalAccessException e) {
            throw BoApiException.validation("AP.VALIDATION_ERROR",
                    "基字段 " + snake + " 在实体上不存在（本体与存量不一致，应被漂移检测拦截）");
        }
    }

    private String availableNames() {
        List<String> names = new ArrayList<>();
        definitions.path("derivedFields").forEach(f -> names.add(f.path("name").asText()));
        return String.join(", ", names);
    }

    private static String snakeToCamel(String s) {
        StringBuilder sb = new StringBuilder();
        for (String part : s.split("_")) {
            if (sb.isEmpty()) {
                sb.append(part);
            } else {
                sb.append(Character.toUpperCase(part.charAt(0))).append(part.substring(1));
            }
        }
        return sb.toString();
    }
}
