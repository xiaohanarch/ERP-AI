package com.erp.ap.service;

import com.erp.ap.boapi.BoApiException;
import com.erp.ap.domain.GoodsReceipt;
import com.erp.ap.domain.GrLine;
import com.erp.ap.domain.PoLine;
import com.erp.ap.domain.PurchaseOrder;
import com.erp.ap.domain.Supplier;
import com.erp.ap.repo.GoodsReceiptRepo;
import com.erp.ap.repo.GrLineRepo;
import com.erp.ap.repo.PoLineRepo;
import com.erp.ap.repo.PurchaseOrderRepo;
import com.erp.ap.repo.SupplierRepo;
import com.erp.ap.security.AuthContext;
import com.erp.ap.security.PermissionService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 采购域只读切片（跨域协同标的）：订单详情与收货取证。
 *
 * 与 AP 域三单匹配的关系：AP 侧只能看到「发票 vs 收货」的差异（如 INV-A-001
 * 开票 120 vs 收货 100），短交还是超开要结合订单量才能定位（PO-A-0001
 * 订单 100 = 已收 100，故为供应商超开）。本服务提供采购侧的取证数据。
 *
 * 权限语义与 AP 域一致：复用存量权限码（ap.po.read / ap.gr.read），
 * 组织范围经 PermissionService 判定（越界按未找到处理，不泄露存在性）。
 */
@Service
@RequiredArgsConstructor
public class ProcurementQueryService {

    private final PurchaseOrderRepo purchaseOrderRepo;
    private final GoodsReceiptRepo goodsReceiptRepo;
    private final PoLineRepo poLineRepo;
    private final GrLineRepo grLineRepo;
    private final SupplierRepo supplierRepo;
    private final PermissionService permissionService;

    /** 订单详情：订单头 + 行明细（订购量/单价）+ 按行汇总的已收量。 */
    public Map<String, Object> poDetail(String poNo) {
        PurchaseOrder po = loadPoInScope(poNo, "ap.po.read");

        List<PoLine> poLines = poLineRepo.findByPoIdOrderByLineNoAsc(po.getId());
        // 已收量按 po_line 汇总（一张 PO 可能多张收货单分批收货）
        Map<Long, BigDecimal> receivedByPoLine = new LinkedHashMap<>();
        for (GoodsReceipt gr : goodsReceiptRepo.findByPoIdOrderByReceiptDateAsc(po.getId())) {
            for (GrLine gl : grLineRepo.findByGrIdOrderByIdAsc(gr.getId())) {
                if (gl.getPoLineId() != null) {
                    receivedByPoLine.merge(gl.getPoLineId(), gl.getQty(), BigDecimal::add);
                }
            }
        }

        List<Map<String, Object>> lines = new ArrayList<>();
        BigDecimal orderTotal = BigDecimal.ZERO;
        for (PoLine pl : poLines) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("lineNo", pl.getLineNo());
            m.put("item", pl.getItem());
            m.put("orderQty", pl.getQty());
            m.put("unitPrice", pl.getUnitPrice());
            m.put("receivedQty", receivedByPoLine.getOrDefault(pl.getId(), BigDecimal.ZERO));
            lines.add(m);
            orderTotal = orderTotal.add(pl.getQty().multiply(pl.getUnitPrice()));
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("poNo", po.getPoNo());
        out.put("status", po.getStatus());
        out.put("orderDate", po.getOrderDate() == null ? null : po.getOrderDate().toString());
        out.put("org", po.getOrg());
        Supplier supplier = po.getSupplierId() == null ? null
                : supplierRepo.findById(po.getSupplierId()).orElse(null);
        out.put("supplier", supplier == null ? null : supplier.getName());
        out.put("orderTotalCny", orderTotal);
        out.put("lines", lines);
        out.put("receivedComplete", poLines.stream().allMatch(pl ->
                receivedByPoLine.getOrDefault(pl.getId(), BigDecimal.ZERO).compareTo(pl.getQty()) >= 0));
        return out;
    }

    /** 收货取证：某订单下的全部收货单（单号/日期/行明细数量）。 */
    public Map<String, Object> grListForPo(String poNo) {
        PurchaseOrder po = loadPoInScope(poNo, "ap.gr.read");

        List<Map<String, Object>> receipts = new ArrayList<>();
        BigDecimal totalReceived = BigDecimal.ZERO;
        for (GoodsReceipt gr : goodsReceiptRepo.findByPoIdOrderByReceiptDateAsc(po.getId())) {
            List<GrLine> glLines = grLineRepo.findByGrIdOrderByIdAsc(gr.getId());
            List<Map<String, Object>> lineMaps = new ArrayList<>();
            for (GrLine gl : glLines) {
                Map<String, Object> lm = new LinkedHashMap<>();
                lm.put("item", gl.getItem());
                lm.put("qty", gl.getQty());
                lineMaps.add(lm);
                totalReceived = totalReceived.add(gl.getQty());
            }
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("grNo", gr.getGrNo());
            m.put("receiptDate", gr.getReceiptDate() == null ? null : gr.getReceiptDate().toString());
            m.put("lines", lineMaps);
            receipts.add(m);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("poNo", po.getPoNo());
        out.put("receiptCount", receipts.size());
        out.put("totalReceivedQty", totalReceived);
        out.put("receipts", receipts);
        return out;
    }

    /** 范围内加载：租户 fail-closed + 权限码 + 组织覆盖（越界按未找到，不泄露存在性）。 */
    private PurchaseOrder loadPoInScope(String poNo, String permissionCode) {
        String tid = AuthContext.get().getTenantId();
        if (tid == null || tid.isBlank()) {
            throw BoApiException.permissionDenied("AP.PERMISSION_DENIED", "缺少租户上下文，拒绝查询");
        }
        PurchaseOrder po = purchaseOrderRepo.findByPoNo(poNo)
                .orElseThrow(() -> BoApiException.notFound("AP.PO_NOT_FOUND",
                        "采购订单不存在或不在您的数据权限范围内"));
        if (!tid.equals(po.getTenantId())) {
            // 跨租越界同样按未找到处理（不泄露存在性）
            throw BoApiException.notFound("AP.PO_NOT_FOUND",
                    "采购订单不存在或不在您的数据权限范围内");
        }
        permissionService.requireCovers(permissionCode, po.getOrg());
        return po;
    }
}
