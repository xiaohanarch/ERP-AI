package com.erp.ap.service;

import com.erp.ap.boapi.BoApiException;
import com.erp.ap.domain.Invoice;
import com.erp.ap.domain.InvoiceLine;
import com.erp.ap.domain.PoLine;
import com.erp.ap.domain.Supplier;
import com.erp.ap.repo.GoodsReceiptRepo;
import com.erp.ap.repo.GrLineRepo;
import com.erp.ap.repo.InvoiceLineRepo;
import com.erp.ap.repo.InvoiceRepo;
import com.erp.ap.repo.PoLineRepo;
import com.erp.ap.repo.PurchaseOrderRepo;
import com.erp.ap.repo.SupplierRepo;
import com.erp.ap.security.AuthContext;
import com.erp.ap.security.PermissionService;
import jakarta.persistence.EntityManager;
import jakarta.persistence.criteria.CriteriaBuilder;
import jakarta.persistence.criteria.CriteriaQuery;
import jakarta.persistence.criteria.Predicate;
import jakarta.persistence.criteria.Root;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.*;

/**
 * 发票查询（UI 列表 / 阻断筛查 / 匹配明细 / 余额指标）。
 * 列表与筛查共用 PermissionService 的组织口径 —— 与页面同集合是平价保证。
 */
@Service
@RequiredArgsConstructor
public class InvoiceQueryService {

    private final InvoiceRepo invoiceRepo;
    private final InvoiceLineRepo invoiceLineRepo;
    private final PoLineRepo poLineRepo;
    private final GrLineRepo grLineRepo;
    private final PurchaseOrderRepo purchaseOrderRepo;
    private final GoodsReceiptRepo goodsReceiptRepo;
    private final SupplierRepo supplierRepo;
    private final PermissionService permissionService;
    private final ValidationService validationService;
    private final EntityManager entityManager;

    /** 页面发票列表（张三口径 = ORG-EAST-PROC 的 50 条）。 */
    public Map<String, Object> uiList() {
        permissionService.require("ap.invoice.read");
        Set<String> orgs = permissionService.accessibleOrgs("ap.invoice.read");
        Specification<Invoice> spec = (root, q, cb) -> {
            List<Predicate> ps = new ArrayList<>();
            ps.add(cb.equal(root.get("tenantId"), currentTenantId()));
            ps.add(cb.equal(root.get("status"), "POSTED"));
            if (orgs != null) {
                ps.add(root.get("org").in(orgs));
            }
            return cb.and(ps.toArray(new Predicate[0]));
        };
        List<Invoice> invoices = invoiceRepo.findAll(spec, PageRequest.of(0, 200, Sort.by("invoiceNo"))).getContent();
        List<Map<String, Object>> items = new ArrayList<>();
        for (Invoice i : invoices) {
            items.add(summaryOf(i));
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", items.size());
        out.put("items", items);
        return out;
    }

    /** 阻断发票批量筛查（游标分页 + 数据权限口径披露 E-2）。 */
    public Map<String, Object> listBlocked(String cursor, Integer pageSize, BigDecimal minAmount) {
        permissionService.require("ap.invoice.read");
        Set<String> orgs = permissionService.accessibleOrgs("ap.invoice.read");

        Specification<Invoice> baseSpec = (root, q, cb) -> {
            List<Predicate> ps = new ArrayList<>();
            ps.add(cb.equal(root.get("tenantId"), currentTenantId()));
            ps.add(cb.equal(root.get("status"), "POSTED"));
            ps.add(cb.equal(root.get("validationStatus"), "BLOCKED"));
            if (orgs != null) {
                ps.add(root.get("org").in(orgs));
            }
            if (minAmount != null) {
                ps.add(cb.greaterThanOrEqualTo(root.get("amountCny"), minAmount));
            }
            return cb.and(ps.toArray(new Predicate[0]));
        };
        long total = invoiceRepo.count(baseSpec);

        Specification<Invoice> pageSpec = baseSpec.and((root, q, cb) -> cursor == null ? null
                : cb.greaterThan(root.get("invoiceNo"), cursor));
        int size = pageSize == null ? 20 : Math.min(Math.max(pageSize, 1), 100);
        List<Invoice> page = invoiceRepo.findAll(pageSpec, PageRequest.of(0, size, Sort.by("invoiceNo"))).getContent();

        List<Map<String, Object>> items = new ArrayList<>();
        for (Invoice i : page) {
            Map<String, Object> item = summaryOf(i);
            item.put("blockedReasons", blockedReasonsOf(i));
            items.add(item);
        }

        Map<String, Object> pageInfo = new LinkedHashMap<>();
        pageInfo.put("total", total);
        pageInfo.put("nextCursor", page.size() == size ? page.get(page.size() - 1).getInvoiceNo() : null);
        pageInfo.put("pageSize", size);
        pageInfo.put("truncated", page.size() == size);

        // E-2 披露：本次结果经过哪些数据权限维度过滤
        Map<String, Object> filtered = new LinkedHashMap<>();
        List<String> dims = new ArrayList<>();
        dims.add("tenant");
        Map<String, Object> applied = new LinkedHashMap<>();
        applied.put("tenant", AuthContext.get().getTenantId());
        if (orgs != null) {
            dims.add("org");
            applied.put("org", orgs);
        }
        filtered.put("dimensions", dims);
        filtered.put("appliedValues", applied);
        filtered.put("note", orgs == null
                ? "结果限定在您的租户内（全组织口径）"
                : "结果限定在您的数据权限组织范围内；租户外与其他组织的数据不可见");

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("pageInfo", pageInfo);
        out.put("filteredByDimension", filtered);
        return out;
    }

    /** 三单匹配差异下钻。 */
    public Map<String, Object> matchDetail(String invoiceNo) {
        Invoice invoice = validationService.loadInvoiceInScope(invoiceNo);
        // PO/GR 权限检查（王五无 po.read -> AP.PO_NOT_ACCESSIBLE）
        if (AuthContext.get().getAuthType() != AuthContext.AuthType.APPID) {
            if (!AuthContext.get().hasPermission("ap.po.read") || !AuthContext.get().hasPermission("ap.gr.read")) {
                String missing = AuthContext.get().hasPermission("ap.po.read") ? "ap.gr.read" : "ap.po.read";
                throw BoApiException.permissionDenied("AP.PO_NOT_ACCESSIBLE",
                        "缺少权限码 " + missing + "，无法查看三单匹配明细");
            }
            permissionService.requireCovers("ap.po.read", invoice.getOrg());
            permissionService.requireCovers("ap.gr.read", invoice.getOrg());
        }

        List<InvoiceLine> lines = invoiceLineRepo.findByInvoiceIdOrderByLineNoAsc(invoice.getId());
        Map<Long, BigDecimal> poPrice = new HashMap<>();
        Map<Long, BigDecimal> grQty = new HashMap<>();
        if (invoice.getPoId() != null) {
            for (PoLine pl : poLineRepo.findByPoIdOrderByLineNoAsc(invoice.getPoId())) {
                poPrice.put(pl.getId(), pl.getUnitPrice());
            }
        }
        if (invoice.getGrId() != null) {
            for (var gl : grLineRepo.findByGrIdOrderByIdAsc(invoice.getGrId())) {
                grQty.put(gl.getId(), gl.getQty());
            }
        }

        List<Map<String, Object>> lineMaps = new ArrayList<>();
        for (InvoiceLine l : lines) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("lineNo", l.getLineNo());
            m.put("item", l.getItem());
            m.put("poQty", l.getPoLineId() == null ? null
                    : poLineRepo.findById(l.getPoLineId()).map(PoLine::getQty).orElse(null));
            m.put("grQty", l.getGrLineId() == null ? null : grQty.get(l.getGrLineId()));
            m.put("invoiceQty", l.getQty());
            m.put("poUnitPrice", l.getPoLineId() == null ? null : poPrice.get(l.getPoLineId()));
            m.put("invoiceUnitPrice", l.getUnitPrice());
            List<String> findings = new ArrayList<>();
            BigDecimal gr = l.getGrLineId() == null ? null : grQty.get(l.getGrLineId());
            if (gr != null && l.getQty().compareTo(gr) > 0) {
                findings.add("AP.MATCH.QTY_MISMATCH");
            }
            BigDecimal po = l.getPoLineId() == null ? null : poPrice.get(l.getPoLineId());
            if (po != null && l.getUnitPrice().compareTo(po) != 0) {
                findings.add("AP.MATCH.PRICE_MISMATCH");
            }
            m.put("findings", findings);
            lineMaps.add(m);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("invoiceNo", invoice.getInvoiceNo());
        out.put("poNo", invoice.getPoId() == null ? null
                : purchaseOrderRepo.findById(invoice.getPoId()).map(p -> p.getPoNo()).orElse(null));
        out.put("grNo", invoice.getGrId() == null ? null
                : goodsReceiptRepo.findById(invoice.getGrId()).map(g -> g.getGrNo()).orElse(null));
        out.put("lines", lineMaps);
        return out;
    }

    /** 余额指标（语义层指标计算唯一出口；口径随响应返回）。 */
    public Map<String, Object> balanceQuery(String metric, String period, String scope) {
        permissionService.require("ap.balance.read");
        BigDecimal confirmed = sumAmount(false, period);
        BigDecimal paid = sumPaid(period);
        BigDecimal accrual = sumAmount(true, period);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("metric", metric);
        out.put("scope", scope == null ? "tenant" : scope);
        out.put("period", period);
        Map<String, Object> components = new LinkedHashMap<>();
        components.put("ap.payable.confirmed", confirmed);
        components.put("ap.payable.paid", paid);
        components.put("ap.payable.accrual", accrual);
        out.put("components", components);

        switch (metric == null ? "" : metric) {
            case "ap.payable.confirmed" -> out.put("valueCny", confirmed);
            case "ap.payable.paid" -> out.put("valueCny", paid);
            case "ap.payable.accrual" -> out.put("valueCny", accrual);
            case "ap.balance.net" -> {
                out.put("valueCny", confirmed.subtract(paid).subtract(accrual));
                out.put("valueCnyExcludingAccrual", confirmed.subtract(paid));
            }
            default -> throw BoApiException.validation("AP.VALIDATION_ERROR", "未知指标：" + metric);
        }
        out.put("caliber", "net = 确认应付 - 已付款 - 暂估；两租户口径差异（是否计入暂估）由语义层 A0 参数解释");
        return out;
    }

    // ---------- 聚合（Criteria 动态构建，避免 JPQL 空参数陷阱） ----------

    /** 租户上下文（fail-closed：缺失即拒绝，绝不退化为全租户可见）。 */
    private String currentTenantId() {
        String tid = AuthContext.get().getTenantId();
        if (tid == null || tid.isBlank()) {
            throw BoApiException.permissionDenied("AP.PERMISSION_DENIED", "缺少租户上下文，拒绝查询");
        }
        return tid;
    }

    private BigDecimal sumAmount(boolean accrualOnly, String period) {
        CriteriaBuilder cb = entityManager.getCriteriaBuilder();
        CriteriaQuery<BigDecimal> q = cb.createQuery(BigDecimal.class);
        Root<Invoice> root = q.from(Invoice.class);
        List<Predicate> ps = new ArrayList<>();
        ps.add(cb.equal(root.get("tenantId"), currentTenantId()));
        ps.add(cb.equal(root.get("status"), "POSTED"));
        ps.add(cb.equal(root.get("isAccrual"), accrualOnly));
        if (period != null && !period.isBlank()) {
            ps.add(cb.equal(root.get("period"), period));
        }
        q.select(cb.coalesce(cb.sum(root.get("amountCny")), BigDecimal.ZERO)).where(ps.toArray(new Predicate[0]));
        BigDecimal r = entityManager.createQuery(q).getSingleResult();
        return r == null ? BigDecimal.ZERO : r;
    }

    private BigDecimal sumPaid(String period) {
        CriteriaBuilder cb = entityManager.getCriteriaBuilder();
        CriteriaQuery<BigDecimal> q = cb.createQuery(BigDecimal.class);
        Root<Invoice> root = q.from(Invoice.class);
        List<Predicate> ps = new ArrayList<>();
        ps.add(cb.equal(root.get("tenantId"), currentTenantId()));
        ps.add(cb.equal(root.get("status"), "POSTED"));
        ps.add(cb.equal(root.get("isAccrual"), false));
        if (period != null && !period.isBlank()) {
            ps.add(cb.equal(root.get("period"), period));
        }
        q.select(cb.coalesce(cb.sum(root.get("paidCny")), BigDecimal.ZERO)).where(ps.toArray(new Predicate[0]));
        BigDecimal r = entityManager.createQuery(q).getSingleResult();
        return r == null ? BigDecimal.ZERO : r;
    }

    // ---------- 辅助 ----------

    private Map<String, Object> summaryOf(Invoice i) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("invoiceNo", i.getInvoiceNo());
        Supplier s = i.getSupplierId() == null ? null : supplierRepo.findById(i.getSupplierId()).orElse(null);
        m.put("supplier", s == null ? null : s.getName());
        m.put("amountCny", i.getAmountCny());
        m.put("org", i.getOrg());
        m.put("status", i.getStatus());
        m.put("validationStatus", i.getValidationStatus());
        m.put("taxCode", i.getTaxCode());
        m.put("period", i.getPeriod());
        return m;
    }

    /** 阻断原因（同样受组级权限裁剪 —— 不向无权限者泄露预算原因）。 */
    private List<String> blockedReasonsOf(Invoice i) {
        List<String> reasons = new ArrayList<>();
        if (i.getSupplierId() != null) {
            Supplier s = supplierRepo.findById(i.getSupplierId()).orElse(null);
            if (s != null && !Boolean.TRUE.equals(s.getQualified()) && hasCode("ap.vendor.read")) {
                reasons.add("AP.VENDOR.NOT_QUALIFIED");
            }
        }
        if (i.getPoId() != null && hasCode("ap.po.read") && hasCode("ap.gr.read") && hasCode("ap.invoice.read")) {
            List<InvoiceLine> lines = invoiceLineRepo.findByInvoiceIdOrderByLineNoAsc(i.getId());
            Map<Long, BigDecimal> grQty = new HashMap<>();
            if (i.getGrId() != null) {
                grLineRepo.findByGrIdOrderByIdAsc(i.getGrId()).forEach(gl -> grQty.put(gl.getId(), gl.getQty()));
            }
            Map<Long, BigDecimal> poPrice = new HashMap<>();
            poLineRepo.findByPoIdOrderByLineNoAsc(i.getPoId()).forEach(pl -> poPrice.put(pl.getId(), pl.getUnitPrice()));
            for (InvoiceLine l : lines) {
                BigDecimal gr = l.getGrLineId() == null ? null : grQty.get(l.getGrLineId());
                if (gr != null && l.getQty().compareTo(gr) > 0) {
                    reasons.add("AP.MATCH.QTY_MISMATCH");
                }
                BigDecimal po = l.getPoLineId() == null ? null : poPrice.get(l.getPoLineId());
                if (po != null && l.getUnitPrice().compareTo(po) != 0) {
                    reasons.add("AP.MATCH.PRICE_MISMATCH");
                }
            }
        }
        if (hasCode("ap.budget.read")) {
            // 预算原因只在拥有预算权限时披露（原生 SQL 显式带租户条件）
            boolean exceeded = false;
            try {
                var rows = entityManager.createNativeQuery(
                                "SELECT budget_amount, occupied_amount FROM budget_occupancy WHERE tenant_id = ? AND org = ? AND period = ?")
                        .setParameter(1, AuthContext.get().getTenantId())
                        .setParameter(2, i.getOrg())
                        .setParameter(3, i.getPeriod())
                        .getResultList();
                if (!rows.isEmpty()) {
                    Object[] row = (Object[]) rows.get(0);
                    BigDecimal remaining = ((BigDecimal) row[0]).subtract((BigDecimal) row[1]);
                    exceeded = i.getAmountCny().compareTo(remaining) > 0;
                }
            } catch (Exception ignored) {
                // 预算原因非关键路径
            }
            if (exceeded) {
                reasons.add("AP.BUDGET.EXCEEDED");
            }
        }
        return reasons;
    }

    private boolean hasCode(String code) {
        return AuthContext.get().hasPermission(code);
    }
}
