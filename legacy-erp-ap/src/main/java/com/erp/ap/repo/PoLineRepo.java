package com.erp.ap.repo;

import com.erp.ap.domain.PoLine;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface PoLineRepo extends JpaRepository<PoLine, Long> {
    List<PoLine> findByPoIdOrderByLineNoAsc(Long poId);
}
