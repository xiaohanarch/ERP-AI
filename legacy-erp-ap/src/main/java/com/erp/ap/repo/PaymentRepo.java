package com.erp.ap.repo;

import com.erp.ap.domain.Payment;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface PaymentRepo extends JpaRepository<Payment, Long> {
    Optional<Payment> findByPaymentOrderNo(String paymentOrderNo);
}
