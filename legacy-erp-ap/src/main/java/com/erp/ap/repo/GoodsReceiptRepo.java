package com.erp.ap.repo;

import com.erp.ap.domain.GoodsReceipt;
import org.springframework.data.jpa.repository.JpaRepository;

public interface GoodsReceiptRepo extends JpaRepository<GoodsReceipt, Long> {
}
