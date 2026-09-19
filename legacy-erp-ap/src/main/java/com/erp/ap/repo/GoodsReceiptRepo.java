package com.erp.ap.repo;

import com.erp.ap.domain.GoodsReceipt;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface GoodsReceiptRepo extends JpaRepository<GoodsReceipt, Long> {

    List<GoodsReceipt> findByPoIdOrderByReceiptDateAsc(Long poId);
}
