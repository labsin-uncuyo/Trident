(function ($) {

  "use strict";

  var init_slider = function() {
    var nav_swiper = new Swiper(".swiper.banner-nav-slider", {
      slidesPerView: "auto",
      spaceBetween: 10,
    });
    
    // banner swiper slide
    var banner_swiper = new Swiper(".swiper.banner-slider", {
      slidesPerView: 1,
      // loop: true,
      speed: 900,
      autoplay: {
        delay: 4000,
      },
      thumbs: {
        swiper: nav_swiper,
      },
    });
    
    // banner bg image swiper
    var image_slider = new Swiper(".swiper.image-slider", {
      slidesPerView: 1,
      speed: 900,
    });
    
    // Update bg image
    function updatePagination() {
      image_slider.slideTo(banner_swiper.activeIndex);
    }
    
    // Listen to slide changes from both sliders
    banner_swiper.on('slideChange', updatePagination);

    // Portfolio Slider
    var swiper = new Swiper(".portfolio-Swiper", {
      slidesPerView: 4,
      spaceBetween: 30,
      pagination: {
        el: ".swiper-pagination",
        clickable: true,
      },
      breakpoints: {
        300: {
          slidesPerView: 2,
        },
        768: {
          slidesPerView: 2,
          spaceBetween: 20,
        },
        1200: {
          slidesPerView: 3,
          spaceBetween: 30,
        },
      },
    });
  }

  // Animate Texts
  var initTextFx = function () {
    $('.txt-fx').each(function () {
      var newstr = '';
      var count = 0;
      var delay = 300;
      var stagger = 10;
      var words = this.textContent.split(/\s/);
      var arrWords = new Array();
      
      $.each( words, function( key, value ) {
        newstr = '<span class="word">';

        for ( var i = 0, l = value.length; i < l; i++ ) {
          newstr += "<span class='letter' style='transition-delay:"+ ( delay + stagger * count ) +"ms;'>"+ value[ i ] +"</span>";
          count++;
        }
        newstr += '</span>';

        arrWords.push(newstr);
        count++;
      });

      this.innerHTML = arrWords.join("<span class='letter' style='transition-delay:"+ delay +"ms;'>&nbsp;</span>");
    });
  }

  // init Isotope
  var initIsotope = function() {
    
    $('.grid').each(function(){

      // $('.grid').imagesLoaded( function() {
        // images have loaded
        var $buttonGroup = $( '.button-group' );
        var $checked = $buttonGroup.find('.is-checked');
        var filterValue = $checked.attr('data-filter');
  
        var $grid = $('.grid').isotope({
          itemSelector: '.portfolio-item',
          // layoutMode: 'fitRows',
          filter: filterValue
        });
    
        // bind filter button click
        $('.button-group').on( 'click', 'a', function(e) {
          e.preventDefault();
          filterValue = $( this ).attr('data-filter');
          $grid.isotope({ filter: filterValue });
        });
    
        // change is-checked class on buttons
        $('.button-group').each( function( i, buttonGroup ) {
          $buttonGroup.on( 'click', 'a', function() {
            $buttonGroup.find('.is-checked').removeClass('is-checked');
            $( this ).addClass('is-checked');
          });
        });
      // });

    });
  }

  // init Chocolat light box
  var initChocolat = function() {
    Chocolat(document.querySelectorAll('.image-link'), {
      imageSize: 'contain',
      loop: true,
    })
  }

  $(document).ready(function () {
    // overlayMenu();
    init_slider();
    initTextFx();
    initChocolat();
    initIsotope();

    // mobile menu
    $('.menu-btn').click(function(e){
      // e.preventDefault();
      $('body').toggleClass('nav-active');
    });

    AOS.init({
      duration: 1200,
      // once: true,
    })

  });

  // preloader
	$(window).load(function() {
		// $("#overlayer").fadeOut("slow");
		$('body').addClass('loaded');
    initIsotope();
	});

})(jQuery);