package com.erp.ap.repo;

import com.erp.ap.domain.PurchaseOrder;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface PurchaseOrderRepo extends JpaRepository<PurchaseOrder, Long> {

    Optional<PurchaseOrder> findByPoNo(String poNo);
}
