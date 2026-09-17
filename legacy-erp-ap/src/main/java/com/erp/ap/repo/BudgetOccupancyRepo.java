package com.erp.ap.repo;

import com.erp.ap.domain.BudgetOccupancy;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface BudgetOccupancyRepo extends JpaRepository<BudgetOccupancy, Long> {
    Optional<BudgetOccupancy> findByOrgAndPeriod(String org, String period);
}
