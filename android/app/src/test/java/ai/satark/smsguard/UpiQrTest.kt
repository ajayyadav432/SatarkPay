package ai.satark.smsguard

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpiQrTest {
    private fun upi(raw: String) = UpiQr.parse(raw) as Scanned.Upi

    @Test fun readsAFullPaymentQr() {
        val q = upi("upi://pay?pa=ramesh.kirana@simaxis&pn=Ramesh%20Kirana&am=180.00&tn=milk&cu=INR")
        assertEquals("ramesh.kirana@simaxis", q.payee)
        assertEquals("Ramesh Kirana", q.name)
        assertEquals(180.0, q.amount!!, 0.001)
        assertEquals("milk", q.note)
    }

    @Test fun aShopQrWithNoAmountAsksThePersonLater() {
        val q = upi("upi://pay?pa=shop@ybl&pn=Shop")
        assertNull(q.amount)
        assertNull(q.note)
    }

    @Test fun capitalLettersAndPlusSignsAreRead() {
        val q = upi("UPI://PAY?PA=Shop.One@YBL&TN=scan+to+receive")
        assertEquals("shop.one@ybl", q.payee)
        assertEquals("scan to receive", q.note)
    }

    @Test fun anAmountThatMakesNoSenseIsDropped() {
        for (bad in listOf("0", "-50", "abc", "NaN", "99999999999")) assertNull(bad, upi("upi://pay?pa=a@ybl&am=$bad").amount)
    }

    @Test fun theFirstPayeeCounts() {
        assertEquals("first@ybl", upi("upi://pay?pa=first@ybl&pa=second@ybl").payee)
    }

    @Test fun aBrokenPercentSignIsNotACrash() {
        assertEquals("100%%20real", upi("upi://pay?pa=a@ybl&tn=100%%20real").note)
        assertEquals("50%", upi("upi://pay?pa=a@ybl&tn=50%").note)
    }

    @Test fun aLongNoteIsCut() {
        assertEquals(200, upi("upi://pay?pa=a@ybl&tn=" + "x".repeat(500)).note!!.length)
    }

    @Test fun aUpiQrWithoutAValidPayeeIsNotAPayment() {
        for (bad in listOf("upi://pay?pn=NoPayee", "upi://pay", "upi://pay?pa=not an id", "upi://pay?pa=@ybl"))
            assertTrue(bad, UpiQr.parse(bad) is Scanned.Other)
    }

    @Test fun aLinkIsALink() {
        assertTrue(UpiQr.parse(" http://sbi-kyc-update.xyz/login ") is Scanned.Link)
        assertTrue(UpiQr.parse("HTTPS://example.com") is Scanned.Link)
    }

    @Test fun anythingElseIsNotAPayment() {
        for (other in listOf("hello", "", "tel:1930", "javascript:alert(1)")) assertTrue(other, UpiQr.parse(other) is Scanned.Other)
    }
}
